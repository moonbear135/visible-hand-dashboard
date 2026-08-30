# tests/test_web_session_isolation.py
"""
🔴 동시 접속 세션 격리 검증 — ENGINEERING_SPEC.md §0-3-8 (이 프로젝트 최상위 금지사항)

오너 지시 원문(2026-08-16): *"개인 자산이 노출 될 수 있는 문제는 집안환경에 따라서 예민하고
분쟁을 일으킬 수 있는 사항이야 … 절대로 개인정보가 꼬여서 노출되는 문제는 발생하면 안되"*

즉 이 테스트가 지키려는 것은 화면의 모양이 아니라 **"서로 다른 브라우저로 동시에 로그인한
두 사람의 보유종목·매입가·손익이 서버 안에서 단 1바이트도 섞이지 않는다"** 하나입니다.
이전 계획서 §9 "4. scorecard" 완료기준 ⑦ — **이 테스트가 실패하면 다른 항목이 전부
통과해도 scorecard 화면은 절대 공개하지 않습니다.**

────────────────────────────────────────────────────────────────────────────
무엇을 어떻게 검증하는가 (그리고 무엇을 못 하는가 — §0-1 정직하게)

  [1] 정적 분석 (AST) — "구조적으로 섞일 수 없는가"
      `web/**/*.py` + `main.py` 를 파싱해서
        · 모듈 최상위(함수/클래스 밖)에 **가변 전역**(dict/list/set)이 새로 생기지 않았는지
          — 읽기 전용 시장데이터 캐시(`web/state.py::_JSON_CACHE`)처럼 안전한 것만 화이트리스트
            (§0-3-8 "읽기 전용 시세 캐시는 전역이어도 안전, 사용자 데이터는 절대 금지" 구분선)
        · 사용자 데이터를 연상시키는 이름(client/user/token/session/holding/…)의 전역이
          **불변 상수 이외의 값**을 갖고 있지 않은지
        · `global` 선언으로 모듈 상태를 다시 묶는 코드가 없는지 (`_client = None` 패턴 차단)
        · 전역 초기화에 `create_supabase_client()` 같은 **사용자 세션을 만드는 호출**이 없는지
        · `app.storage.*` 를 만지는 코드가 `web/auth.py` 의 접근자 2개 안에만 있는지
      → 이 검사들은 "지금 코드가 맞다"가 아니라 **"앞으로 누가 잘못 고치면 즉시 잡힌다"**는
        회귀 안전망이 목적입니다.

  [2] 동작 시뮬레이션 — "실제로 호출해봐도 안 섞이는가"
      `web/auth.py` 의 `get_client()` / `login()` / `logout()` 을 **진짜로 호출**합니다.
      NiceGUI 의 `app.storage.user` / `app.storage.client` 자리에 "가짜 접속 A / B / C" 의
      dict 를 꽂아 넣고(=`web/auth.py` 가 저장소 접근을 함수 2개로 모아둔 이유),
      A로 로그인 → B로 로그인 → A 로그아웃 순서로 진행하며 매 단계마다
      "상대방 서랍이 그대로인지"를 확인합니다.

  [3] 화면 배선 검사 — `web/pages/scorecard_page.py` 가 client/user_id 를 **인자로** 받는지,
      전역에서 사용자를 추측하는 코드가 없는지, XSS 이스케이프·차트 높이 등.

  [5]~[7] 2026-08-17(5단계) 추가 — 로그인이 필요한 **두 번째 화면**
      `web/pages/report_page.py`(사장님 보고서)에 [3]과 같은 기준을 그대로 적용하고,
      표·기간이동을 실제로 실행해 보며(스모크), 두 화면이 **같은 로그인 세션**을 쓰는지를
      함께 검증합니다. 로그인이 필요한 화면이 늘어날 때마다 이 목록도 같이 늘립니다.

  ⚠️ 이 샌드박스에서 **검증하지 못한 것**(배포 후 오너 실기기 확인 필요):
      · 진짜 NiceGUI 서버 프로세스에서 `app.storage.client` 가 접속마다 실제로 다른 dict 를
        돌려주는지(= NiceGUI 내부 contextvar 동작 자체). 이 테스트는 "우리 코드가 그 두 저장소를
        올바르게 구분해서 쓰는가"까지만 증명합니다. NiceGUI 자체 동작은 프레임워크의 문서화된
        계약(`storage.client` = 접속별, `storage.user` = 쿠키별)에 의존합니다.
      · 실제 Supabase RLS 가 남의 행을 막는지(그건 DB 계층 — sql/scorecard_schema.sql 과
        tests/test_scorecard.py 가 담당).

실행: python tests/test_web_session_isolation.py
"""

import ast
import asyncio
import io
import os
import re
import sys
import types
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))          # from _render_helpers import run_render

# 🔴 2026-08-30 재감사(테스트 스위트) S-1 — 렌더 스모크 4건이 슬롯 컨텍스트 전파 없이
# `asyncio.run()`을 직접 써서, 이 프로세스의 1회용 "유사 클라이언트"를 소진하면 실행 순서에
# 따라 서로 연쇄 실패했습니다(`tests/_render_helpers.py::run_render()`의 M-6 발견과 동일한
# 근본 원인 — 그 수정 당시 `test_scorecard_public_ui.py`/`test_scorecard_ocr.py`만 채택하고
# 이 "가장 중요한 테스트"(§0-3-8) 파일은 빠져 있었습니다). 이 파일의 렌더 스모크도 같은
# 공용 헬퍼를 쓰도록 옮깁니다(§0-3-10 — 이미 있는 해법 재사용, 새로 만들지 않음).
from _render_helpers import run_render                                   # noqa: E402

FAILURES = []

import pytest


@pytest.fixture(autouse=True)
def _assert_no_check_failures():
    """
    🔴 2026-08-21 발견 — `check()`는 실패를 `FAILURES`에 기록만 하고, 그 목록을 실제로
    검사해서 죽는 코드는 파일 맨 아래 `if __name__ == "__main__": main()` 안에만 있었습니다.
    이 파일의 모든 검증은 pytest로 돌려왔는데, pytest는 `main()`을 절대 부르지 않으므로
    `check()` 실패가 있어도 각 `test_*` 함수는 스스로 실패하지 않았습니다 — 이 파일의
    배선·렌더 스모크 검사가 그동안 pytest 상에서는 항상 초록불이었다는 뜻입니다
    (2026-08-21, 결투다! USD 화면 작업 중 발견).

    그래서 매 테스트 앞뒤로 `FAILURES`의 증가분을 직접 확인해 pytest에서도 똑같이
    실패하게 만듭니다. 기존 `test_*` 함수는 한 줄도 안 고쳤습니다 — 이 fixture 하나가
    파일 안의 모든 테스트에 자동 적용됩니다(pytest의 `autouse` 규약).
    """
    start = len(FAILURES)
    yield
    new_failures = FAILURES[start:]
    assert not new_failures, f"check() 로 기록된 실패 {len(new_failures)}건: {new_failures}"



def check(condition, label, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        FAILURES.append(label)


# =============================================================================
# 검사 대상 파일 (NiceGUI 표현 계층 전체)
# =============================================================================
def target_files():
    files = sorted(p for p in (REPO_ROOT / "web").rglob("*.py") if "__pycache__" not in p.parts)
    files.append(REPO_ROOT / "main.py")
    # 🌐 2026-08-17 — `utils/data_source.py` 는 `utils/` 에 있지만 **접속자 전원이 공유하는
    #    전역 캐시**를 들고 있으므로(원격 스냅샷 텍스트), web/ 과 똑같은 §0-3-8 검사를 받게
    #    합니다. "읽기 전용 시장데이터만 담긴다"가 앞으로도 유지되는지 자동으로 감시합니다.
    files.append(REPO_ROOT / "utils" / "data_source.py")
    return files


def rel(path):
    return path.relative_to(REPO_ROOT).as_posix()


def python_code_only(src):
    """주석·독스트링을 걷어낸 파이썬 '실행되는 코드'만 남깁니다.

    (설명 주석에 `st.session_state` 같은 문구가 적혀 있다고 실제로 그 경로가 있는 건
     아니므로, "코드에 없는지"를 볼 때는 반드시 이걸 통과시킨 문자열로 확인합니다.
     `tests/test_report.py` 의 같은 이름 함수와 동일한 규칙입니다.)
    """
    without_docstrings = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)
    return "\n".join(line for line in without_docstrings.splitlines()
                     if not line.strip().startswith("#"))


def _calls_with_client_first_arg(tree, call_name):
    """`call_name(client, …)` 를 찾되, **직접 호출**과 `run_blocking(call_name, client, …)`
    로 감싼 호출을 **둘 다** 인정합니다.

    🔴 2026-08-21 발견 — 이 검사들은 전부 `web/blocking.py::run_blocking()` 리팩터
    (이벤트 루프가 막히지 않게 동기 DB 호출을 스레드로 넘기는 수정, 같은 날 적용) **이전**에
    쓰여서, "client 를 명시적으로 넘기는가"라는 검사 목적은 그대로인데 호출 모양만
    `call_name(client, …)` → `run_blocking(call_name, client, …)` 로 바뀐 걸 못 잡고
    있었습니다. pytest 가 그동안 이 실패를 실제로 죽이지 않았던 `check()`/`FAILURES` 버그
    (2026-08-21 발견) 뒤에 숨어 있다가, 그 버그를 고치고 나서야 드러났습니다 — 화면 코드가
    잘못된 게 아니라 이 검사가 낡았던 것입니다.
    """
    direct = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == call_name
              and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "client"]
    wrapped = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "run_blocking"
               and len(n.args) >= 2
               and isinstance(n.args[0], ast.Name) and n.args[0].id == call_name
               and isinstance(n.args[1], ast.Name) and n.args[1].id == "client"]
    return direct + wrapped


def module_level_statements(tree):
    """모듈 최상위 스코프의 문장들 (try/if/with/for 안까지 들어가되, 함수·클래스 안은 제외).

    `try: import plotly ... except ImportError: PLOTLY_AVAILABLE = False` 처럼 조건부로
    선언되는 전역도 전역이므로 함께 봅니다. 반대로 함수 안의 지역변수는 접속마다 새로
    만들어지므로 검사 대상이 아닙니다.
    """
    out = []
    stack = list(tree.body)
    while stack:
        node = stack.pop(0)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        out.append(node)
        for field in ("body", "orelse", "finalbody"):
            stack.extend(getattr(node, field, []) or [])
        for handler in getattr(node, "handlers", []) or []:
            stack.extend(handler.body)
    return out


def assigned_names(node):
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    else:
        return []
    return [t.id for t in targets if isinstance(t, ast.Name)]


# =============================================================================
# [1-a] 모듈 최상위 가변 전역 — 화이트리스트에 없으면 실패
# =============================================================================
#  ⚠️ 여기에 새 항목을 추가하려면 **왜 이 전역이 사용자 데이터를 담을 수 없는지**를 사유로
#     적으세요. "지금은 안 담는다"가 아니라 "구조적으로 담길 수 없다"여야 합니다.
#     (§0-3-8 — 읽기 전용 시세 데이터는 전역이 정답, 사용자 데이터는 절대 금지)
ALLOWED_MUTABLE_GLOBALS = {
    ("web/state.py", "_JSON_CACHE"):
        "읽기 전용 시장 데이터(data/*.json) 캐시. 모든 접속자에게 동일한 시세이며 "
        "개인정보가 아님 (§0-3-8 구분선 · 계획서 §3-3 규칙 4). 키는 파일 경로뿐.",
    ("utils/data_source.py", "_CACHE"):
        "원격에서 받아온 `data/*.json` **본문 텍스트**와 그 메타데이터(ETag·마지막 성공시각) "
        "캐시. 키는 저장소 기준 상대경로 문자열뿐이고, 값에 들어가는 것은 모든 접속자에게 "
        "동일한 시세 스냅샷 텍스트입니다. 사용자별 데이터는 이 모듈을 거치는 경로 자체가 "
        "없습니다 — `read_text()` 는 `data/` 안의 파일 경로만 받습니다 (§0-3-8 구분선).",
    ("web/components/widgets.py", "_BANNER_PALETTE"):
        "배너 색상 상수표(문자열 튜플). 값이 CSS 색상 문자열이라 데이터가 들어갈 자리가 없음.",
    ("web/layout.py", "_MENU_GROUPS"):
        "메뉴 정의(그룹 제목 · [경로·라벨·관리자전용 플래그] 목록). 고정 문자열/불리언뿐 "
        "(2026-08-18 — 예전 Streamlit처럼 그룹으로 묶어 보기 편하게 바꾸며 `_MENU` 에서 이름 변경).",
    ("web/layout.py", "_MENU"):
        "위 `_MENU_GROUPS` 를 펼친 하위호환용 평평한 목록. 값 출처가 같아 고정 문자열/불리언뿐.",
    ("web/pages/pegy_page.py", "FILTER_PRESETS"):
        "필터 드롭다운 항목(고정 문자열 목록).",
    ("web/pages/us_stocks_page.py", "FILTER_PRESETS"):
        "필터 드롭다운 항목(고정 문자열 목록).",
    ("web/pages/scorecard_page.py", "CURRENCY_TITLES"):
        "통화 코드 → 소제목 문구(고정 문자열).",
    # (2026-08-17 제거) `("web/pages/scorecard_page.py", "_CHART_LAYOUT")` 와
    #  `("web/pages/macro_page.py", "_CHART_LAYOUT")` 두 항목은 그 전역이 사라져서 뺐습니다.
    #  두 화면이 거의 같은 사전을 각각 들고 있던 것을 `web/components/widgets.py::chart_layout()`
    #  **함수**로 합쳤고(§0-3-10), 함수는 호출할 때마다 새 dict 를 만들어 돌려주므로
    #  모듈 전역 가변 상태가 애초에 생기지 않습니다(§0-3-8 관점에서도 더 안전).
    ("web/pages/report_page.py", "MARKET_TITLES"):
        "시장 코드 → 소제목 문구(고정 문자열). 사용자 데이터가 들어갈 자리가 없음.",
    # ── 6단계(macro) 이식분 — 전부 `views/macro_view.py` 에서 글자 그대로 옮긴 **설명 상수**
    #    입니다. 이 화면은 로그인이 없고(관리자 비밀번호 게이트만 있음) 사용자별 데이터를
    #    아예 다루지 않습니다 — 읽는 건 모든 관리자에게 동일한 `market_history.csv` 와
    #    `data/macro_commentary.json` 뿐이라 §0-3-8 의 "읽기 전용 시장데이터" 쪽입니다.
    #    (원본 `views/macro_view.py` 와의 글자 단위 대조는 2026-08-29 Streamlit 은퇴로 종료.)
    ("web/pages/macro_page.py", "layers"):
        "위험 점수 구간(0~10층) → 라벨·권장 비중 문구(고정 문자열 튜플). 값이 대입되는 코드가 없음.",
    ("web/pages/macro_page.py", "FRIENDLY_NAMES"):
        "지표 내부키 → 화면 표기명(고정 문자열). 사용자 데이터가 들어갈 자리가 없음.",
    ("web/pages/macro_page.py", "STUDY_ONLY_INDICATORS"):
        "점수에서 뺀 지표들의 '공부용' 설명 텍스트(고정 문자열). 어떤 값도 계산·저장하지 않음.",
    ("web/pages/macro_page.py", "DROPPED_AS_DUPLICATE"):
        "개념 중복으로 완전 제외한 지표 2개의 사유 문구(고정 문자열 튜플).",
    # ── ⚔️ 결투다!(5번째 모듈, 2026-08-24 재번호) 화면 — 2026-08-20 추가 ───────────────────────
    ("web/pages/duel_page.py", "WINDOW_TITLES"):
        "계좌 유형 코드(M1/M3/M6) → 화면 표기명(고정 문자열). 값이 대입되는 코드가 없고, "
        "사용자별 계좌·주문·현금은 전부 @ui.page 함수 안의 지역 변수이거나 함수 인자로만 "
        "흐릅니다(아래 [9] 가 매번 확인).",
    ("web/pages/duel_page.py", "_MARKET_SUFFIX_TEXT"):
        "코스피+코스닥 통합 상위 500 확대(2026-08-26, TASK_HISTORY #151 후속) 후 오너 요청 — "
        "종목 빠른 검색 드롭다운에 시장 라벨 표시. market 코드('KOSPI'/'KOSDAQ') → 고정 "
        "텍스트 접미사 2개뿐인 상수표. 값이 대입되는 코드가 없고, 사용자별 데이터가 들어갈 "
        "자리도 없음(코드 그 자체가 아니라 화면 표기 문구만 담음).",
    # ── 💼 "내 성적표" 공개 계층 화면 2종 — 2026-08-23 추가 ────────────────────
    #    🗑️ 이 자리에 있던 `web/pages/duel_consent_page.py` ·
    #       `web/pages/duel_leaderboard_page.py` 항목 4개는 두 화면이 **파일째 은퇴**하면서
    #       함께 뺐습니다(공개 대상이 결투 가상계좌 성적에서 "내 성적표" 실제 보유 자산으로
    #       바뀐 전환 — `tests/test_duel_public_ui.py` [3] 이 그 은퇴를 고정합니다).
    #       아래 두 항목이 그 자리를 이어받습니다 — 성격(값이 대입되지 않는 고정 문구표)은
    #       같고, 창유형(M1/M3/M6) 축이 사라져 `WINDOW_TITLES` 는 아예 없습니다.
    ("web/pages/scorecard_consent_page.py", "CONSENT_ITEM_SENTENCES"):
        "동의 항목 6개(2026-08-23 에 5개 → 6개)의 **고정 문구**(항목 이름 · 무엇이 "
        "공개되는지 한 문장). 키는 "
        "scorecard_publish_db.CONSENT_ITEM_FLAGS 와 같아야 하며(그 사실을 "
        "consent_item_rows() 가 매번 확인), 값이 대입되는 코드가 없습니다. 사용자별 동의 "
        "상태는 전부 함수 인자로만 흐릅니다(client·user_id 를 인자로 받는 함수들).",
    ("web/pages/scorecard_leaderboard_page.py", "CURRENCY_TITLES"):
        "통화 코드(KRW/USD) → 화면 표기명(고정 문자열). `web/pages/scorecard_page.py` 의 "
        "같은 이름 상수와 성격이 같고, 값이 대입되는 코드가 없습니다. 통화 코드 자체는 "
        "`utils/scorecard_db.py` 의 CURRENCY_KRW/CURRENCY_USD 가 단일 출처이며, '지금 어느 "
        "통화를 보고 있는가'는 전부 `_render_body()` 안의 지역 dict(`view`)로만 흐릅니다 "
        "(§0-3-8 — 접속자끼리 선택 상태가 섞이지 않습니다).",
    # ── 📈 보조지표 "여기서부터는 신앙입니다" 화면 — 2026-08-25 추가 ────────────────────
    #    5개 전부 지표 내부 코드(RSI/MACD/Bollinger 종류, overbought/golden/inside 같은
    #    상태값) → 화면 표시용 한글 라벨·배지 색(고정 문자열/색상 코드 튜플) 매핑입니다.
    #    값의 출처는 `utils/indicators.py`의 반환값이고(단일 출처, §0-3-10), 여기서는
    #    표시만 담당합니다. 5개 전부 `.get()`/인덱싱으로만 읽히고, 대입·update 하는 코드가
    #    파일 안에 없습니다 — 사용자별 종목 상태는 매 렌더 호출의 지역 변수로만 흐릅니다.
    ("web/pages/indicator_page.py", "_INDICATOR_LABELS"):
        "지표 코드(RSI/MACD/Bollinger) → 화면 표기명(고정 문자열). 값이 대입되는 코드가 없음.",
    ("web/pages/indicator_page.py", "_RSI_SIGNAL_LABELS"):
        "RSI 판정값(overbought/oversold/neutral) → 한글 설명 라벨(고정 문자열).",
    ("web/pages/indicator_page.py", "_MACD_CROSS_LABELS"):
        "MACD 교차 판정값(golden/dead) → 한글 설명 라벨(고정 문자열).",
    ("web/pages/indicator_page.py", "_BB_POSITION_LABELS"):
        "볼린저밴드 위치 판정값(above_upper/below_lower/inside) → 한글 설명 라벨(고정 문자열).",
    ("web/pages/indicator_page.py", "_STATE_BADGE_STYLES"):
        "위 판정값들 → 배지 색상(배경·글자·테두리 헥스코드 튜플). 새 색을 발명하지 않고 "
        "기존 배지 팔레트 관례를 재사용(§0-3-10). 값이 대입되는 코드가 없음.",
}

_MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque"}


def _is_mutable_value(value):
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        return name in _MUTABLE_CALLS
    return False


def test_no_mutable_globals():
    print("\n[1-a] 모듈 최상위 가변 전역 (사용자 데이터가 숨을 수 있는 유일한 자리)")
    found = 0
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in module_level_statements(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            if not _is_mutable_value(getattr(node, "value", None)):
                continue
            for name in assigned_names(node):
                found += 1
                key = (rel(path), name)
                check(
                    key in ALLOWED_MUTABLE_GLOBALS,
                    f"{rel(path)}:{node.lineno} 전역 `{name}` (가변 컨테이너) 이 허용 목록에 있음",
                    "← 사용자 데이터를 담을 수 있는 새 전역입니다. 페이지 함수의 지역변수로 "
                    "옮기거나, 정말 읽기 전용 시장데이터라면 ALLOWED_MUTABLE_GLOBALS 에 사유와 "
                    "함께 등록하세요 (§0-3-8).",
                )
    check(found >= len(ALLOWED_MUTABLE_GLOBALS),
          f"검사기가 실제로 전역을 훑고 있음(발견 {found}건)",
          "← 0건이면 파서가 아무것도 못 보고 있다는 뜻이라 검사 자체가 무의미합니다.")


# =============================================================================
# [1-b] 사용자 데이터를 연상시키는 이름의 전역은 '불변 상수'만 허용
# =============================================================================
USER_DATA_TOKENS = (
    "client", "user", "token", "session", "holding", "portfolio", "profile",
    "auth", "login", "email", "password", "credential", "account", "asset", "secret",
)

# 이름에 위 단어가 들어가지만 사용자 데이터가 아닌 것 — 사유와 함께 명시적으로 허용합니다.
ALLOWED_USER_NAMED_GLOBALS = {
    ("main.py", "STORAGE_SECRET"):
        "NiceGUI 쿠키 서명키(서버 전체에 하나). 특정 사용자의 데이터가 아니며 환경변수에서 "
        "읽어 ui.run() 에 한 번 넘기고 끝. 값이 로그·화면에 출력되는 경로가 없음(§0-3-9).",
}


def _is_immutable_constant(value):
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Tuple):
        return all(isinstance(e, ast.Constant) for e in value.elts)
    if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
        return True
    return False


def test_user_named_globals_are_constants():
    print("\n[1-b] 사용자 데이터 이름의 전역은 불변 상수(문자열/숫자)만 허용")
    inspected = 0
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in module_level_statements(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                continue
            for name in assigned_names(node):
                if not any(token in name.lower() for token in USER_DATA_TOKENS):
                    continue
                inspected += 1
                key = (rel(path), name)
                if key in ALLOWED_USER_NAMED_GLOBALS:
                    check(True, f"{rel(path)}:{node.lineno} 전역 `{name}` — 사유 등록된 예외")
                    continue
                check(
                    _is_immutable_constant(getattr(node, "value", None)),
                    f"{rel(path)}:{node.lineno} 전역 `{name}` 이 불변 상수임(데이터를 담을 수 없음)",
                    "← 사용자 데이터를 연상시키는 이름의 전역에 상수가 아닌 값이 대입됐습니다. "
                    "이런 이름은 저장소 키(문자열 상수)일 때만 전역에 둘 수 있습니다 (§0-3-8).",
                )
    check(inspected >= 2,
          f"이름 기반 검사가 실제로 동작 중(대상 {inspected}건)",
          "← web/auth.py 의 SB_TOKENS_KEY/SB_CLIENT_KEY 만으로도 2건 이상이어야 정상입니다.")


# =============================================================================
# [1-c] `global` 선언 금지 + 전역 초기화에서 세션 생성 호출 금지
# =============================================================================
FORBIDDEN_GLOBAL_CALLS = {
    "create_supabase_client", "get_client", "new_auth_client", "login", "sign_in",
    "current_user", "fetch_holdings", "add_lot", "user_storage", "client_storage",
}


def test_no_global_rebinding():
    print("\n[1-c] `global` 재바인딩 금지 · 전역 초기화에서 세션 생성 금지")
    global_stmts = []
    bad_calls = []
    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                global_stmts.append(f"{rel(path)}:{node.lineno} global {', '.join(node.names)}")
        for node in module_level_statements(tree):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    if name in FORBIDDEN_GLOBAL_CALLS:
                        bad_calls.append(f"{rel(path)}:{sub.lineno} {name}()")

    check(not global_stmts,
          "`global` 선언이 한 곳도 없음 (`_client = None` + `global _client` 패턴 차단)",
          f"발견: {global_stmts}")
    check(not bad_calls,
          "모듈 로딩 시점에 사용자 세션을 만드는 호출이 없음",
          f"발견: {bad_calls} ← import 시 만들어진 객체는 전 접속자가 공유합니다(§0-3-8).")


# =============================================================================
# [1-d] app.storage 접근 지점은 web/auth.py 의 접근자 2개뿐
# =============================================================================
def test_storage_access_is_centralised():
    print("\n[1-d] app.storage 접근 지점 집중 (감사 지점 1곳)")
    offenders = []
    accessor_hits = set()

    for path in target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 함수별로 훑어서 "어느 함수 안에서 app.storage 를 만졌는지" 를 기록합니다.
        parents = {}
        for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for sub in ast.walk(func):
                parents[id(sub)] = func.name

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            # `app.storage.user` / `app.storage.client` → Attribute(value=Attribute(value=Name('app')))
            base = node.value
            if not (isinstance(base, ast.Attribute) and base.attr == "storage"
                    and isinstance(base.value, ast.Name) and base.value.id == "app"):
                continue
            owner = parents.get(id(node))
            where = f"{rel(path)}:{node.lineno} (함수 {owner})"
            if rel(path) == "web/auth.py" and owner in ("user_storage", "client_storage"):
                accessor_hits.add(owner)
            else:
                offenders.append(where)

    check(not offenders,
          "app.storage 를 직접 만지는 코드가 web/auth.py 의 접근자 2개 밖에 없음",
          f"발견: {offenders} ← 저장소 접근을 흩뿌리면 어느 접속의 서랍인지 추적할 수 없게 "
          "되고, 자동 검증도 불가능해집니다 (§0-3-8).")
    check(accessor_hits == {"user_storage", "client_storage"},
          "web/auth.py 의 user_storage()/client_storage() 가 각각 app.storage 를 읽고 있음",
          f"실제: {sorted(accessor_hits)}")


# =============================================================================
# [2] 동작 시뮬레이션 — 가짜 접속 A / B / C 로 실제 함수 호출
# =============================================================================
def _install_nicegui_stub():
    """nicegui 미설치 환경에서도 web/ 모듈을 import 할 수 있게 최소 스텁을 주입합니다.

    (이 함수는 nicegui가 **없을 때만** 스텁을 깔고, 있으면 바로 `return False`로 빠집니다
     — 실제 서버를 띄우는 대신 저장소 접근자만 바꿔치기하는 설계는 그대로입니다. 2026-08-30
     재감사(테스트 스위트) S-1: 이 기기에는 실제로 nicegui가 설치돼 있어(requirements.txt
     명시) 이 스텁은 평소 켜지지 않습니다 — 아래 주석은 "샌드박스에 nicegui를 설치할 수
     없다"고 돼 있었지만 더 이상 사실이 아니라 정정합니다. 스텁은 nicegui 자체가 없는
     극단적 환경을 위한 방어적 대비책으로 남겨둡니다. 자세한 한계는 이 파일 맨 위 주석 참고.)
    """
    try:
        import nicegui  # noqa: F401
        return False
    except ImportError:
        pass

    class _Storage:
        def __init__(self):
            self.user = {}
            self.client = {}

    class _App:
        def __init__(self):
            self.storage = _Storage()

        def get(self, *_a, **_k):                 # @app.get('/healthz') 데코레이터용
            return lambda fn: fn

    class _Element:
        """어떤 위젯 흉내든 다 내는 객체 — 호출/속성접근/`with` 를 전부 받아넘깁니다.

        덕분에 화면 함수를 **실제로 실행**해볼 수 있습니다([4] 렌더 스모크 테스트).
        위젯이 그려지진 않지만 f-string·이스케이프·분기·계산은 전부 진짜로 돌아갑니다.
        """

        def __call__(self, *args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]                    # 데코레이터로 쓰인 경우
            return self

        def __getattr__(self, _name):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    element = _Element()

    class _Refreshable:
        """`@ui.refreshable` 흉내 — `.refresh()` 를 가진 호출 가능 객체여야 합니다."""

        def __init__(self, fn):
            self.fn = fn

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

        def refresh(self, *_a, **_k):
            return None                           # 스모크 테스트에서는 재귀 렌더를 하지 않습니다

    class _UI(types.ModuleType):
        refreshable = staticmethod(_Refreshable)

        def __getattr__(self, _name):
            return element

    class _Run(types.ModuleType):
        """`nicegui.run` 흉내 — `await run.io_bound(fn, *a, **kw)` 를 그냥 동기 호출로
        대체합니다. 오프라인 테스트에는 진짜 스레드풀/이벤트루프가 없으니 이걸로 충분하고,
        중요한 건 `web/pages/scorecard_page.py` 의 `from nicegui import run, ui` 임포트가
        깨지지 않는 것입니다(2026-08-17, 로그인 버튼 로딩 표시 수정분).
        """

        @staticmethod
        async def io_bound(fn, *args, **kwargs):
            return fn(*args, **kwargs)

    nicegui = types.ModuleType("nicegui")
    nicegui.app = _App()
    nicegui.ui = _UI("nicegui.ui")
    nicegui.run = _Run("nicegui.run")
    sys.modules["nicegui"] = nicegui
    sys.modules["nicegui.ui"] = nicegui.ui
    sys.modules["nicegui.run"] = nicegui.run
    return True


class FakeConnection:
    """가짜 '접속' 하나 = 서로 완전히 분리된 서랍 두 개.

    실제 NiceGUI 에서는 `app.storage.user`(쿠키별) / `app.storage.client`(접속별)가
    이 역할을 합니다. 시크릿창을 새로 열면 쿠키가 다르므로 `user` 서랍부터 완전히 별개입니다.
    """

    def __init__(self, name):
        self.name = name
        self.user = {}
        self.client = {}


class FakeAuth:
    def __init__(self, owner):
        self.owner = owner
        self.session_token = None

    def set_session(self, access_token, refresh_token):
        self.owner.restored_with = (access_token, refresh_token)
        self.session_token = access_token

    def sign_out(self):
        self.session_token = None
        self.owner.signed_out = True


class FakeSupabaseClient:
    """Supabase 클라이언트 흉내. **중요한 건 이 객체가 로그인 세션을 품는다는 사실**입니다 —
    그래서 이 객체가 두 접속에서 같은 인스턴스면 그 자체가 사고입니다."""

    def __init__(self, serial):
        self.serial = serial
        self.auth = FakeAuth(self)
        self.restored_with = None
        self.signed_out = False

    def __repr__(self):
        return f"<FakeSupabaseClient #{self.serial} token={self.auth.session_token}>"


def test_two_sessions_do_not_mix():
    print("\n[2] 동작 시뮬레이션 — 가짜 접속 A/B/C 동시 로그인")
    _install_nicegui_stub()
    import web.auth as auth

    created = []

    def fake_create_client():
        client = FakeSupabaseClient(len(created) + 1)
        created.append(client)
        return client

    signed_in_on = []

    class _Session:
        def __init__(self, email):
            self.access_token = f"ACCESS::{email}"
            self.refresh_token = f"REFRESH::{email}"

    class _User:
        def __init__(self, email):
            self.email = email
            self.id = f"uid-{email}"

    class _Response:
        def __init__(self, email):
            self.session = _Session(email)
            self.user = _User(email)

    def fake_sign_in(client, email, password):
        # 진짜 supabase-py 도 로그인에 성공하면 **그 클라이언트 객체 안에** 세션을 붙입니다.
        # (바로 이 성질 때문에 클라이언트를 공유하면 남의 권한으로 DB를 읽게 됩니다 — §0-3-8)
        signed_in_on.append((client, email))
        client.auth.session_token = f"ACCESS::{email}"
        return _Response(email)

    def fake_sign_out(client):
        client.auth.sign_out()

    active = {"conn": None}

    # ── 여기가 이 테스트의 핵심 장치 ────────────────────────────────────────
    # web/auth.py 가 저장소 접근을 함수 2개로 모아둔 덕분에, 실제 서버 없이도
    # "지금 요청을 보낸 접속"을 바꿔가며 진짜 login()/get_client()/logout() 을 호출할 수 있습니다.
    original = (auth.user_storage, auth.client_storage,
                auth.create_supabase_client, auth.sign_in, auth.sign_out)
    auth.user_storage = lambda: active["conn"].user
    auth.client_storage = lambda: active["conn"].client
    auth.create_supabase_client = fake_create_client
    auth.sign_in = fake_sign_in
    auth.sign_out = fake_sign_out

    try:
        conn_a = FakeConnection("A(아빠 폰)")
        conn_b = FakeConnection("B(다른 사람의 시크릿창)")
        conn_c = FakeConnection("C(로그인 안 한 방문자)")

        # ── 1. A 로그인 ──────────────────────────────────────────────────
        # ⚠️ 2026-08-17 — login() 이 이제 async def 입니다(배포 후 "로그인이 안 된다"
        # 사고 원인 수정 — web/auth.py 의 login() docstring 참고: 저장소 접근은 이벤트
        # 루프에서, 네트워크 호출 한 줄만 run.io_bound 로). 테스트도 asyncio.run 으로 부릅니다.
        active["conn"] = conn_a
        user_a = asyncio.run(auth.login("a@example.com", "pw-a"))
        check(getattr(user_a, "email", None) == "a@example.com", "A 로그인 성공")
        check(conn_a.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::a@example.com", "refresh_token": "REFRESH::a@example.com"},
              "A의 토큰이 A의 저장소에만 들어감")
        check(conn_b.user == {}, "B의 저장소는 여전히 비어 있음 (A 로그인이 B에게 새지 않음)")
        check(conn_c.user == {} and conn_c.client == {}, "C의 저장소도 비어 있음")

        client_a = auth.get_client()
        check(conn_a.client.get(auth.SB_CLIENT_KEY) is client_a,
              "A의 클라이언트는 A의 접속 저장소(app.storage.client)에 보관됨")
        check(conn_b.client == {}, "B의 접속 저장소에는 클라이언트가 생기지 않음")

        # ── 2. B 로그인 (A가 로그인해 있는 동안) ─────────────────────────
        active["conn"] = conn_b
        asyncio.run(auth.login("b@example.com", "pw-b"))
        client_b = auth.get_client()

        check(conn_b.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::b@example.com", "refresh_token": "REFRESH::b@example.com"},
              "B의 토큰이 B의 저장소에 들어감")
        check(conn_a.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::a@example.com", "refresh_token": "REFRESH::a@example.com"},
              "🔴 B의 로그인 후에도 A의 토큰이 그대로 (덮어쓰기·오염 없음)")
        check(client_a is not client_b,
              "🔴 A와 B가 서로 다른 Supabase 클라이언트 객체를 받음 (같은 객체면 즉시 사고)")
        check(client_a.auth.session_token != client_b.auth.session_token,
              "🔴 두 클라이언트가 서로 다른 세션 토큰을 들고 있음")

        # 로그인 호출이 각자의 클라이언트에만 일어났는지
        check([c for c, _ in signed_in_on] == [client_a, client_b],
              "sign_in() 이 각 접속 자신의 클라이언트에만 호출됨",
              f"실제: {signed_in_on}")

        # ── 3. 같은 접속에서 다시 부르면 같은 객체(캐시), 다른 접속이면 다른 객체 ──
        active["conn"] = conn_a
        check(auth.get_client() is client_a, "같은 접속에서 get_client() 는 같은 객체를 재사용")
        active["conn"] = conn_b
        check(auth.get_client() is client_b, "다른 접속에서는 여전히 자기 객체")

        # ── 4. 로그인 안 한 접속 C ───────────────────────────────────────
        active["conn"] = conn_c
        check(auth.has_supabase_session() is False, "C는 로그인 상태가 아님")
        client_c = auth.get_client()
        check(client_c is not client_a and client_c is not client_b,
              "C도 자기만의 클라이언트를 받음")
        check(client_c.restored_with is None,
              "🔴 C의 클라이언트에는 어떤 세션도 복원되지 않음 (남의 토큰이 붙지 않음)")
        check(client_c.auth.session_token is None, "C의 클라이언트는 미로그인 상태")

        # ── 5. 새로고침 시나리오 — 접속 저장소만 비우고 다시 열기 ────────
        # (실제 NiceGUI 에서 새로고침하면 storage.client 는 폐기되고 storage.user 는 남습니다)
        active["conn"] = conn_a
        conn_a.client.clear()
        client_a2 = auth.get_client()
        check(client_a2 is not client_a, "새로고침 후에는 새 클라이언트가 만들어짐")
        check(client_a2.restored_with ==
              ("ACCESS::a@example.com", "REFRESH::a@example.com"),
              "🔴 새로고침 후 복원되는 토큰은 **A 자신의 것** (로그인 유지 + 남의 토큰 아님)")

        # ── 6. A 로그아웃 — B는 영향 없음 ────────────────────────────────
        active["conn"] = conn_a
        auth.logout()
        check(auth.SB_TOKENS_KEY not in conn_a.user, "A 로그아웃 후 A의 토큰이 지워짐")
        check(auth.SB_CLIENT_KEY not in conn_a.client, "A 로그아웃 후 A의 클라이언트가 폐기됨")
        check(client_a2.signed_out is True, "A의 클라이언트에 실제로 sign_out 이 호출됨")
        check(conn_b.user.get(auth.SB_TOKENS_KEY) ==
              {"access_token": "ACCESS::b@example.com", "refresh_token": "REFRESH::b@example.com"},
              "🔴 A의 로그아웃이 B의 로그인 상태를 건드리지 않음")
        active["conn"] = conn_b
        check(auth.has_supabase_session() is True, "B는 계속 로그인 상태")
        check(auth.get_client() is client_b, "B의 클라이언트도 그대로 살아 있음")

        # ── 7. 만료된 세션 복원 실패 시 토큰을 남겨두지 않는가 ───────────
        conn_expired = FakeConnection("D(만료된 토큰)")
        conn_expired.user[auth.SB_TOKENS_KEY] = {"access_token": "X", "refresh_token": "Y"}
        active["conn"] = conn_expired

        def _boom(*_a, **_k):
            raise RuntimeError("refresh token expired")

        original_create = auth.create_supabase_client

        def _create_broken():
            client = fake_create_client()
            client.auth.set_session = _boom
            return client

        auth.create_supabase_client = _create_broken
        try:
            auth.get_client()
        finally:
            auth.create_supabase_client = original_create
        check(auth.SB_TOKENS_KEY not in conn_expired.user,
              "세션 복원 실패 시 죽은 토큰을 저장소에 남기지 않음 (로그인 안 된 상태로 정직하게 복귀)")

        # ── 8. 모듈 전역에 클라이언트가 새어나가지 않았는가 ──────────────
        leaked = _find_leaked_objects(auth, created)
        check(not leaked,
              "🔴 web/auth.py 모듈 전역 어디에도 Supabase 클라이언트가 남아있지 않음",
              f"발견: {leaked}")

    finally:
        (auth.user_storage, auth.client_storage,
         auth.create_supabase_client, auth.sign_in, auth.sign_out) = original


def _find_leaked_objects(module, objects):
    """모듈 전역(그리고 전역 dict/list 안 1단계)에 대상 객체가 참조되고 있는지 찾습니다."""
    wanted = {id(o) for o in objects}
    leaked = []
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if id(value) in wanted:
            leaked.append(name)
        elif isinstance(value, dict):
            for key, item in value.items():
                if id(item) in wanted:
                    leaked.append(f"{name}[{key!r}]")
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if id(item) in wanted:
                    leaked.append(f"{name}[…]")
    return leaked


# =============================================================================
# [3] 화면 배선 — scorecard_page.py 가 client/user_id 를 인자로 받는가
# =============================================================================
def test_scorecard_page_wiring():
    print("\n[3] web/pages/scorecard_page.py 배선")
    path = REPO_ROOT / "web" / "pages" / "scorecard_page.py"
    check(path.exists(), "web/pages/scorecard_page.py 존재")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # ⚠️ "이 낱말이 코드에 없는지"를 볼 때는 **주석·독스트링을 걷어낸** 문자열로 확인합니다
    # ([5]/[9] 와 같은 이유 — 2026-08-21 이벤트 루프 수정 설명 주석이 "app.storage" 라는
    #  낱말 자체를 언급하고 있어서, 원문(src)으로 검사하면 그 설명에 걸려 항상 실패합니다).
    code = python_code_only(src)

    # (a) DB를 만지는 함수는 client·user_id 를 **인자로** 받아야 합니다 (§0-3-8 함수 설계 원칙)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_render_body", "_render_portfolio", "_render_input_form",
                 "_render_currency_block", "_render_row_manager", "_render_edit_card", "_delete"):
        node = funcs.get(name)
        args = [a.arg for a in node.args.args] if node else []
        check(node is not None and "client" in args and "user_id" in args,
              f"`{name}()` 이 client·user_id 를 인자로 받음", f"실제 인자: {args}")

    # (b) DB 호출에 client 가 첫 인자로 들어가는지 (전역에서 추측하지 않는지)
    for call_name in ("fetch_holdings", "add_lot", "update_holding", "delete_holding"):
        calls = _calls_with_client_first_arg(tree, call_name)
        check(bool(calls),
              f"`{call_name}(client, …)` — 클라이언트를 명시적으로 넘김 (직접 또는 run_blocking 경유)",
              f"호출 {len(calls)}건")

    # (c) 저장소 직접 접근 금지 (web/auth.py 를 통해서만)
    # ⚠️ 2026-08-17 — `from nicegui import ui` 고정 문자열 대신 정규식을 씁니다.
    #    `from nicegui import run, ui`(로그인 버튼 로딩 표시 수정, run.io_bound 사용)처럼
    #    같은 줄에서 다른 이름과 같이 임포트해도 이 검사가 오탐(false positive)으로
    #    실패하면 안 됩니다 — 이 검사의 목적은 "app.storage 직접 접근 여부"이지 임포트
    #    문구 형태가 아닙니다.
    check(bool(re.search(r'from nicegui import[^\n]*\bui\b', src)) and "app.storage" not in code,
          "화면 파일은 app.storage 를 직접 만지지 않음 (web/auth.py 경유)")

    # (d) XSS — 사용자/DB 문자열이 HTML 로 나가는 곳은 esc() 통과 (§0-3-9)
    check("esc(" in src, "HTML 출력에 esc() 사용")
    check("stock_name" not in src or "_row_label_html" in src,
          "종목명은 이스케이프하는 전용 함수(_row_label_html)를 거침")

    # (e) 완료기준 ③④⑤ 관련 회귀 방지
    check("@ui.refreshable" in src, "부분 갱신(@ui.refreshable) 사용 — 전체 리렌더 없음 (완료기준 ③)")
    check(src.count("no-wrap") >= 2 and "flex-1 min-w-0" in src and "shrink-0" in src,
          "'종목 관리' 줄이 항상 한 줄 유지되는 flex 패턴 사용 (완료기준 ④, #127~#130)")
    # 2026-08-18 오너 피드백 — 조각 안에 "종목명+비율"을 같이 넣으면 작은 조각에서 글자가
    # 겹쳐 읽을 수 없었고, 조각 색과 글자 색 대비도 부족했습니다. 원형차트를 Streamlit 원본과
    # 글자 단위로 똑같이 유지하던 걸 그만두고 의도적으로 아래처럼 바꿨습니다(더 이상 "원본과
    # 동일"이 완료기준이 아닙니다 — §0-1, 낡은 완료기준을 그대로 두면 실제로는 통과해야 할
    # 의도된 변경이 계속 실패로 잡힙니다):
    #   · 조각 안 글자는 비율만(이름은 범례로), 어두운 고정색 글자로 밝은 조각에서도 읽히게
    #   · 조각 사이에 어두운 윤곽선을 둘러 경계를 또렷하게
    #   · 범례가 아래로 옮겨가며 세로 공간이 더 필요해져 높이를 h-80(320px)→h-96(384px)로 키움
    check("ui.plotly(fig).classes('w-full h-96')" in src,
          "원형차트에 높이(h-96)를 명시 — 안 주면 0px 로 그려짐, 범례가 아래로 옮겨가며 키움 "
          "(완료기준 ⑤, 2026-08-18 갱신)")
    check("px.pie(names=names, values=values, hole=0.35)" in src
          and 'textinfo="percent"' in src
          and 'color="#0f172a"' in src
          and 'line=dict(color="#0f172a", width=2)' in src,
          "원형차트 figure 생성 — px.pie·hole=0.35는 유지, 조각 안 글자는 비율만+어두운 "
          "고정색(대비 확보), 조각 사이 윤곽선 추가 (2026-08-18 가시성 개선, 의도된 변경)")

    # (f) 원/달러 분리 (완료기준 ⑥) — 통화별로 따로 그리는 구조인지
    check('for currency in ("KRW", "USD")' in src,
          "통화별로 블록을 나눠 그림 (원/달러 합산 경로 없음, 완료기준 ⑥)")
    check("NO_FX_CONVERSION_NOTICE" in src, "환율 변환 없음 고지를 화면에 표시")

    # (g) Streamlit 잔재가 섞여 들어오지 않았는지
    check("import streamlit" not in src and "st.session_state" not in src,
          "Streamlit 코드가 섞여 있지 않음")

    # (h) 예외 원문·트레이스백 노출 방지 (§0-3-4)
    check("_fail(" in src and "traceback" not in src,
          "예상 못 한 예외는 화면에 원문을 흘리지 않고 로그로만 보냄 (§0-3-4)")


# =============================================================================
# [4] 렌더 스모크 테스트 — 로그인 후 본문을 **실제로 실행**해봅니다
# =============================================================================
#  위젯은 스텁이라 화면이 그려지진 않지만, f-string 조립·HTML 이스케이프·손익 계산·통화 분리
#  분기는 전부 진짜로 실행됩니다. 오타(NameError)·잘못된 키 접근(KeyError)·이스케이프 누락을
#  배포 전에 잡는 것이 목적입니다.
#  ⚠️ 보유종목은 **합성 데이터**이고 DB 호출은 대체합니다(§0-1 — 실데이터를 지어내지 않고,
#     실제 Supabase 에 접속하지도 않습니다). 시세는 저장소의 실제 스냅샷을 읽기만 합니다.
# =============================================================================
SYNTHETIC_HOLDINGS = [
    {"id": "row-kr-1", "market": "KR", "ticker": "005930", "stock_name": "삼성전자",
     "quantity": 10.0, "avg_purchase_price": 70000.0, "currency": "KRW"},
    # 유니버스 밖 + XSS 시도 문자열이 종목명에 들어간 경우 (§0-3-9 — 그대로 실행되면 안 됨)
    {"id": "row-kr-2", "market": "KR", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3.0,
     "avg_purchase_price": 1000.0, "currency": "KRW"},
    {"id": "row-us-1", "market": "US", "ticker": "NVDA", "stock_name": "NVIDIA Corp",
     "quantity": 2.0, "avg_purchase_price": 100.0, "currency": "USD"},
]


def test_render_smoke():
    print("\n[4] 로그인 후 본문 렌더 스모크 테스트 (합성 보유종목)")
    _install_nicegui_stub()
    import web.pages.scorecard_page as page

    captured_html = []
    import web.components.widgets as widgets
    from nicegui import ui

    original_fetch = page.fetch_holdings
    original_html = ui.html
    page.fetch_holdings = lambda client, user_id: [dict(h) for h in SYNTHETIC_HOLDINGS]

    def _capture_html(content='', *a, **k):
        captured_html.append(str(content))
        return original_html(content, *a, **k)

    ui.html = _capture_html
    widgets.ui.html = _capture_html                # widgets 모듈이 참조하는 것도 같은 스텁
    try:
        # 2026-08-21 — `_render_body()` 가 `async def` 입니다(스냅샷 6개를 `run.io_bound` 로
        # 읽어 이벤트 루프를 막지 않게 한 수정). 검사 내용은 그대로이고 부르는 방법만 바뀝니다.
        run_render(page._render_body(object(), "uid-test", "a@example.com"))
        check(True, "_render_body() 가 예외 없이 끝까지 실행됨")
    except Exception as exc:                       # noqa: BLE001
        check(False, "_render_body() 가 예외 없이 끝까지 실행됨", f"({type(exc).__name__}: {exc})")
    finally:
        page.fetch_holdings = original_fetch
        ui.html = original_html
        widgets.ui.html = original_html

    blob = "\n".join(captured_html)
    check(bool(blob), "렌더 중 HTML 이 실제로 만들어짐", f"(조각 {len(captured_html)}개)")
    check("<img src=x onerror=" not in blob,
          "🔐 종목명에 심어둔 <img onerror=...> 가 HTML 로 살아나오지 않음 (§0-3-9 XSS)")
    check("&lt;img src=x onerror=alert(1)&gt;" in blob,
          "🔐 그 문자열이 이스케이프되어 '글자 그대로' 출력됨")
    check("현재가 없음" in blob,
          "유니버스 밖 종목(999999)은 값을 지어내지 않고 '현재가 없음' 으로 표시 (§0-1)")


# =============================================================================
# [5] 화면 배선 — web/pages/report_page.py (5단계 · 사장님 보고서)
# =============================================================================
#  '내 성적표'와 **같은 로그인 세션**을 쓰는 두 번째 화면이라, [3] 과 같은 기준을 그대로
#  적용합니다. 로그인이 필요한 화면이 늘어날 때마다 이 검사를 함께 늘립니다(§0-3-8).
# =============================================================================
def test_report_page_wiring():
    print("\n[5] web/pages/report_page.py 배선 (사장님 보고서)")
    path = REPO_ROOT / "web" / "pages" / "report_page.py"
    check(path.exists(), "web/pages/report_page.py 존재")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # ⚠️ "이 낱말이 코드에 없는지"를 볼 때는 **주석·독스트링을 걷어낸** 문자열로 확인합니다.
    #    이 파일은 "Streamlit 의 _consume_pending_ref_date 우회가 왜 필요 없어졌는지"를
    #    주석으로 길게 설명하고 있어서, 원문으로 검사하면 그 설명 자체에 걸려 항상 실패합니다.
    code = python_code_only(src)

    # (a) DB를 만지는 함수는 client·user_id 를 **인자로** 받아야 합니다 (§0-3-8 함수 설계 원칙)
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_render_signed_in", "_render_report_body"):
        node = funcs.get(name)
        args = [a.arg for a in node.args.args] if node else []
        check(node is not None and "client" in args and "user_id" in args,
              f"`{name}()` 이 client·user_id 를 인자로 받음", f"실제 인자: {args}")

    # (b) DB 호출에 client 가 첫 인자로 들어가는지 (전역에서 추측하지 않는지)
    for call_name in ("fetch_user_snapshots", "fetch_user_holding_snapshots"):
        calls = _calls_with_client_first_arg(tree, call_name)
        check(bool(calls),
              f"`{call_name}(client, …)` — 클라이언트를 명시적으로 넘김 (직접 또는 run_blocking 경유)",
              f"호출 {len(calls)}건")

    # (c) 저장소 직접 접근 금지 (web/auth.py 를 통해서만)
    check(bool(re.search(r'from nicegui import[^\n]*\bui\b', src)) and "app.storage" not in code,
          "화면 파일은 app.storage 를 직접 만지지 않음 (web/auth.py 경유)")

    # (d) 🔑 로그인 공유 — '내 성적표'와 **같은 세션 함수·같은 로그인 폼**을 쓰는지
    check("has_supabase_session" in code and "from web.auth import" in code,
          "로그인 여부를 web/auth.py 의 접속자 저장소로 판단 (scorecard 와 동일 경로 = 세션 공유)")
    check("from web.auth_ui import" in code and "render_auth()" in code,
          "로그인 폼을 web/auth_ui.py 공용 함수로 그림 (화면마다 폼을 복붙하지 않음, §0-3-10)")
    for forbidden in ("sign_in(", "sign_up(", "SESSION_USER_KEY", "set_session("):
        check(forbidden not in code,
              f"자체 로그인 처리(`{forbidden}`)를 따로 만들지 않음 — 인증 경로는 web/auth.py 하나")

    # (e) XSS — 사용자/DB 문자열이 HTML 로 나가는 곳은 esc() 통과 (§0-3-9)
    check("esc(" in src, "HTML 출력에 esc() 사용")
    check("stock_name" not in src or "_holding_label_html" in src,
          "종목명은 이스케이프하는 전용 함수(_holding_label_html)를 거침")

    # (f) 🔴 Streamlit 위젯 키 우회 코드가 통째로 사라졌는지 (계획서 §4-2)
    for leftover in ("_consume_pending_ref_date", "pending_ref_date", "REF_DATE_WIDGET_KEY",
                     "st.session_state", "st.rerun", "import streamlit"):
        check(leftover not in code,
              f"Streamlit 잔재 `{leftover}` 가 없음 (위젯 키 우회는 지역변수+refresh 로 대체)")
    check("@ui.refreshable" in code and ".refresh()" in code,
          "기간 이동/기간 변경이 부분 갱신(@ui.refreshable + .refresh())으로 동작")

    # (g) 계산은 utils/report_db.py 가 하고 화면은 그리기만 하는지 (계층 분리)
    check("from utils.report_db import" in code and "PERIOD_OPTIONS" in code,
          "6기간 목록·계산 함수를 utils/report_db.py 에서 그대로 가져다 씀(문자열 이중 관리 금지)")
    check("resolve_display_date" in code and "period_title" in code,
          "주말·공휴일 대체(#117) 판정을 기존 함수로 하고 두 날짜를 화면에 밝힘")

    # (h) 예외 원문·트레이스백 노출 방지 (§0-3-4)
    check("_fail(" in src and "traceback" not in src,
          "예상 못 한 예외는 화면에 원문을 흘리지 않고 로그로만 보냄 (§0-3-4)")


# =============================================================================
# [6] 사장님 보고서 렌더 스모크 — 표·기간이동을 **실제로 실행**해봅니다
# =============================================================================
#  ⚠️ 스냅샷은 **합성 데이터**이고 DB 호출은 대체합니다(§0-1 — 실 Supabase 에 접속하지 않음).
#     벤치마크만 저장소의 실제 `market_history.csv` 를 읽으므로, 아래 기대값(+5.80%)은
#     그 파일의 실측 코스피 종가(2026-07-31 6595.45 → 2026-08-14 6977.94)에서 나옵니다.
# =============================================================================
SYNTHETIC_SNAPSHOTS = [
    {"snapshot_date": "2026-07-31", "market": "KR", "currency": "KRW",
     "total_value": 700000, "total_cost": 703000, "holdings_count": 2, "priced_count": 2,
     "unpriced_count": 0, "benchmark_symbol": "KOSPI", "benchmark_value": 6595.45,
     "price_as_of_kst": "2026-07-31 16:05"},
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW",
     "total_value": 723300, "total_cost": 703000, "holdings_count": 2, "priced_count": 2,
     "unpriced_count": 0, "benchmark_symbol": "KOSPI", "benchmark_value": 6358.95,
     "price_as_of_kst": "2026-08-03 16:05"},
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW",
     "total_value": 750000, "total_cost": 700000, "holdings_count": 2, "priced_count": 1,
     "unpriced_count": 1, "benchmark_symbol": "KOSPI", "benchmark_value": 6977.94,
     "price_as_of_kst": "2026-08-14 16:05"},
]

SYNTHETIC_HOLDING_SNAPSHOTS = [
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW", "ticker": "005930",
     "stock_name": "삼성전자", "quantity": 10, "avg_purchase_price": 70000, "cost": 700000,
     "current_price": 72000, "market_value": 720000, "priced": True,
     "price_as_of_kst": "2026-08-03 16:05"},
    # 종목명에 XSS 시도 문자열이 들어간 경우 (§0-3-9 — 그대로 실행되면 안 됨)
    {"snapshot_date": "2026-08-03", "market": "KR", "currency": "KRW", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3, "avg_purchase_price": 1000,
     "cost": 3000, "current_price": 1100, "market_value": 3300, "priced": True,
     "price_as_of_kst": "2026-08-03 16:05"},
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW", "ticker": "005930",
     "stock_name": "삼성전자", "quantity": 10, "avg_purchase_price": 70000, "cost": 700000,
     "current_price": 75000, "market_value": 750000, "priced": True,
     "price_as_of_kst": "2026-08-14 16:05"},
    # 그날 가격을 몰랐던 종목 — 0 이 아니라 '가격 모름'/'모름' 으로 나와야 합니다(§0-1)
    {"snapshot_date": "2026-08-14", "market": "KR", "currency": "KRW", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3, "avg_purchase_price": 1000,
     "cost": 3000, "current_price": None, "market_value": None, "priced": False,
     "price_as_of_kst": "2026-08-14 16:05"},
]


# 🇺🇸 미국 블록 — 벤치마크 두 줄 + **평균 한 줄**(#116)과 한글 종목명(#115) 확인용.
#    날짜는 저장소의 실제 `data/us_index_history.json` 에 들어 있는 거래일을 씁니다
#    (SPY 773.26 → 776.34 = +0.40% / ONEQ 105.184 → 105.32 = +0.13% / 평균 +0.26%).
SYNTHETIC_US_SNAPSHOTS = [
    {"snapshot_date": "2026-08-07", "market": "US", "currency": "USD",
     "total_value": 10000, "total_cost": 9000, "holdings_count": 1, "priced_count": 1,
     "unpriced_count": 0, "benchmark_symbol": "SP500_PROXY_SPY", "benchmark_value": 773.26,
     "price_as_of_kst": "2026-08-08 06:10"},
    {"snapshot_date": "2026-08-14", "market": "US", "currency": "USD",
     "total_value": 10500, "total_cost": 9000, "holdings_count": 1, "priced_count": 1,
     "unpriced_count": 0, "benchmark_symbol": "SP500_PROXY_SPY", "benchmark_value": 776.34,
     "price_as_of_kst": "2026-08-15 06:10"},
]

SYNTHETIC_US_HOLDINGS = [
    # 스냅샷에는 **영문 원문**이 저장돼 있고, 화면은 '내 성적표'와 같은 한글명으로 보여야 합니다(#115).
    {"snapshot_date": "2026-08-07", "market": "US", "currency": "USD", "ticker": "NVDA",
     "stock_name": "NVIDIA Corp", "quantity": 2, "avg_purchase_price": 4500, "cost": 9000,
     "current_price": 5000, "market_value": 10000, "priced": True,
     "price_as_of_kst": "2026-08-08 06:10"},
    {"snapshot_date": "2026-08-14", "market": "US", "currency": "USD", "ticker": "NVDA",
     "stock_name": "NVIDIA Corp", "quantity": 2, "avg_purchase_price": 4500, "cost": 9000,
     "current_price": 5250, "market_value": 10500, "priced": True,
     "price_as_of_kst": "2026-08-15 06:10"},
]


def _capture_report_render(period, ref_date,
                           snapshots=SYNTHETIC_SNAPSHOTS, holdings=SYNTHETIC_HOLDING_SNAPSHOTS):
    """리포트 본문을 스텁 위에서 실제로 그려 보고, 만들어진 HTML 조각을 모아 돌려줍니다."""
    _install_nicegui_stub()
    import web.pages.report_page as page
    import web.components.widgets as widgets
    from nicegui import ui

    captured = []
    original_html = ui.html
    original_snapshots = page.fetch_user_snapshots
    original_holdings = page.fetch_user_holding_snapshots

    def _capture(content='', *a, **k):
        captured.append(str(content))
        return original_html(content, *a, **k)

    # ⚠️ 실제 `fetch_user_*` 는 DB 행을 `sort_snapshots()` / `sort_holding_snapshots()` 로
    #    정규화해서 돌려줍니다(날짜는 date, 숫자는 float). 화면이 그 규약 위에서 돌기 때문에
    #    가짜 조회도 **같은 정규화를 거쳐** 돌려줘야 진짜와 같은 조건이 됩니다.
    from utils.report_db import sort_holding_snapshots, sort_snapshots
    page.fetch_user_snapshots = lambda client, user_id, **kw: sort_snapshots(snapshots)
    page.fetch_user_holding_snapshots = \
        lambda client, user_id, **kw: sort_holding_snapshots(holdings)
    ui.html = _capture
    widgets.ui.html = _capture
    try:
        # 2026-08-21 — `_render_report_body()` 가 `async def` 입니다(미국 유니버스 스냅샷을
        # `run.io_bound` 로 읽게 한 수정). 부르는 방법만 바뀌고 검사 내용은 그대로입니다.
        run_render(page._render_report_body(object(), "uid-test", period, ref_date))
        error = None
    except Exception as exc:                       # noqa: BLE001
        error = exc
    finally:
        page.fetch_user_snapshots = original_snapshots
        page.fetch_user_holding_snapshots = original_holdings
        ui.html = original_html
        widgets.ui.html = original_html
    return "\n".join(captured), error


def test_report_render_smoke():
    print("\n[6] 사장님 보고서 렌더 스모크 (합성 스냅샷)")
    import datetime

    # ── 월간 (2026-08-14 기준) ────────────────────────────────────────────
    blob, error = _capture_report_render("MONTHLY", datetime.date(2026, 8, 14))
    check(error is None, "_render_report_body() 가 예외 없이 끝까지 실행됨",
          f"({type(error).__name__}: {error})" if error else "")
    check(bool(blob), "렌더 중 HTML 이 실제로 만들어짐")
    check("<img src=x onerror=" not in blob,
          "🔐 종목명에 심어둔 <img onerror=...> 가 HTML 로 살아나오지 않음 (§0-3-9 XSS)")
    check("&lt;img src=x onerror=alert(1)&gt;" in blob,
          "🔐 그 문자열이 이스케이프되어 '글자 그대로' 출력됨")
    check("750,000원" in blob, "기간 종료 평가금액이 스냅샷 값 그대로 표시됨")
    check("+7.14%" in blob,
          "평가금액 변화율이 계산 함수 결과와 일치 (700,000 → 750,000)")
    check("+5.80%" in blob,
          "벤치마크(코스피 6595.45 → 6977.94) 수익률이 실측 CSV 값으로 계산됨")
    check("가격 모름" in blob and "모름" in blob,
          "그날 가격을 몰랐던 종목을 0 이 아니라 '가격 모름'/'모름' 으로 표시 (§0-1)")
    check("대조 불일치" not in blob,
          "종목별 합계(750,000)와 같은 날 합계 스냅샷이 일치해 경고가 뜨지 않음")
    check("비중 변화" in blob or "%p" in blob, "비중 변화 표가 그려짐(기록이 이틀 이상)")

    # ── 일간 · 주말(기록 없는 날) → 가장 최근 기록일로 대체 (#117) ────────
    blob_sun, error_sun = _capture_report_render("DAILY", datetime.date(2026, 8, 16))
    check(error_sun is None, "일간(주말) 렌더도 예외 없이 실행됨",
          f"({type(error_sun).__name__}: {error_sun})" if error_sun else "")
    check("2026-08-16" in blob_sun and "2026-08-14" in blob_sun,
          "주말 대체 안내가 **고른 날과 실제로 보여주는 날 둘 다** 밝힘 (#117 · §0-1)")
    check("저장된 기록이 없는 날" in blob_sun, "대체 안내 문구가 그대로 이식됨")

    # ── 🇺🇸 미국 주간 — 벤치마크 2종 + 평균 한 줄(#116) + 한글 종목명(#115) ─
    import datetime as _dt
    blob_us, error_us = _capture_report_render(
        "WEEKLY", _dt.date(2026, 8, 14),
        snapshots=SYNTHETIC_US_SNAPSHOTS, holdings=SYNTHETIC_US_HOLDINGS)
    check(error_us is None, "미국 블록도 예외 없이 렌더됨",
          f"({type(error_us).__name__}: {error_us})" if error_us else "")
    check("+0.40%" in blob_us and "+0.13%" in blob_us,
          "벤치마크 두 줄이 실측 ETF 종가(SPY 773.26→776.34 / ONEQ 105.184→105.32)로 계산됨")
    check("+0.26%" in blob_us and "평균" in blob_us,
          "미국 두 벤치마크 **평균 한 줄**(#116)이 두 값의 산술평균으로 나옴")
    check("엔비디아" in blob_us and "NVIDIA Corp" not in blob_us,
          "미국 종목명이 '내 성적표'와 같은 한글 표기로 나옴 (#115 — 저장된 영문 원문 아님)")
    check("$10,500.00" in blob_us,
          "달러 금액이 통화 기호 그대로 표시됨 (환율 변환·원화 합산 없음)")


def test_report_period_navigation():
    """'◀ 이전 / 최신 / 다음 ▶' — Streamlit 의 pending 우회 없이 지역 상태만으로 동작하는가."""
    print("\n[6-b] 기간 이동 버튼 (위젯 키 우회 코드 없이)")
    _install_nicegui_stub()
    import datetime
    import web.pages.report_page as page

    class _FakeInput:
        def __init__(self, value):
            self.value = value

    class _FakeBody:
        def __init__(self):
            self.refreshed = 0

        def refresh(self):
            self.refreshed += 1

    view = {"period": "MONTHLY", "ref_date": datetime.date(2026, 8, 17)}
    date_input, body = _FakeInput("2026-08-17"), _FakeBody()

    page._shift_ref_date(view, -1, date_input, body)
    check(view["ref_date"] == datetime.date(2026, 7, 1) and date_input.value == "2026-07-01",
          "◀ 이전 기간: 기준일과 **달력 칸 값이 함께** 바뀜(= 화면에 즉시 반영)",
          f"실제: {view['ref_date']} / {date_input.value}")
    check(body.refreshed == 1, "본문이 한 번 다시 그려짐")

    page._shift_ref_date(view, 1, date_input, body)
    check(view["ref_date"] == datetime.date(2026, 8, 1) and date_input.value == "2026-08-01",
          "다음 기간 ▶ 로 되돌아옴(기간 시작일 기준 — shift_period 규약 그대로)")

    page._apply_ref_date(view, datetime.date(2026, 8, 1), date_input, body)
    check(body.refreshed == 2, "같은 날짜를 다시 넣으면 다시 그리지 않음(무한 루프 방지)")

    page._on_date_typed(view, "이건날짜가아님", date_input, body)
    check(date_input.value == "2026-08-01" and view["ref_date"] == datetime.date(2026, 8, 1),
          "달력 칸에 이상한 값이 들어오면 날짜를 지어내지 않고 직전 기준일로 되돌림 (§0-1)")

    page._apply_period(view, "DAILY", body)
    check(view["period"] == "DAILY" and body.refreshed == 3, "기간 종류 변경이 본문을 다시 그림")


def test_login_is_shared_between_scorecard_and_report():
    """🔑 '내 성적표'와 '사장님 보고서'가 **같은 로그인 세션**을 쓰는가 (오너 확정 사항).

    Streamlit 에서는 두 화면이 같은 `session_state` 키를 공유해서 맞췄지만, NiceGUI 에서는
    두 화면이 **같은 함수(web/auth.py)** 를 부르기만 하면 저장소가 접속자 단위라 자동으로
    공유됩니다. 그래서 여기서 확인하는 것은 두 가지입니다.
      ① 두 화면이 참조하는 세션 함수·로그인 폼이 **같은 객체**인가 (다른 사본이면 언젠가
         한쪽만 고쳐져 두 화면의 로그인 상태가 어긋납니다)
      ② 한 접속에서 로그인하면 그 접속의 저장소 하나로 **양쪽 게이트가 함께 열리는가**,
         그리고 다른 접속(B)은 그대로 닫혀 있는가 (§0-3-8 — 공유는 같은 사람 안에서만)
    """
    print("\n[7] 🔑 내 성적표 ↔ 사장님 보고서 로그인 공유")
    _install_nicegui_stub()
    import web.auth as auth
    import web.auth_ui as auth_ui
    import web.pages.report_page as report
    import web.pages.scorecard_page as scorecard

    check(report.has_supabase_session is scorecard.has_supabase_session is auth.has_supabase_session,
          "두 화면이 **같은** has_supabase_session() 을 봄 (로그인 판정 단일 출처)")
    # 🔴 2026-08-21 — 두 화면 모두 `get_client()` 대신 `get_client_async()` 로 옮겨갔습니다
    # (이벤트 루프 안 막힘 수정, `web/auth.py` 독스트링). 두 화면이 **같은** 접속 전용
    # Supabase 클라이언트 접근 경로를 쓰는지가 이 검사의 목적이므로, 지금 실제로 쓰는
    # 이름(get_client_async)을 봅니다 — `get_client` 는 이제 화면 모듈에 아예 없습니다.
    check(report.get_client_async is scorecard.get_client_async is auth.get_client_async,
          "두 화면이 **같은** get_client_async() 를 씀 (접속 전용 Supabase 클라이언트 1개)")
    check(report.render_auth is scorecard.render_auth is auth_ui.render_auth,
          "두 화면이 **같은** 로그인 폼을 그림 (web/auth_ui.py 하나 — §0-3-10)")

    conn_a, conn_b = FakeConnection("A"), FakeConnection("B")
    active = {"conn": conn_a}
    original = (auth.user_storage, auth.client_storage)
    auth.user_storage = lambda: active["conn"].user
    auth.client_storage = lambda: active["conn"].client
    try:
        # '내 성적표'에서 로그인한 상태를 흉내 냅니다(토큰이 접속자 저장소에 들어간 상태).
        conn_a.user[auth.SB_TOKENS_KEY] = {"access_token": "A", "refresh_token": "A-r"}
        check(report.has_supabase_session() is True,
              "🔑 /scorecard 에서 로그인해 두면 /report 도 로그인 상태 (폼 없이 본문)")
        active["conn"] = conn_b
        check(report.has_supabase_session() is False and scorecard.has_supabase_session() is False,
              "🔴 다른 접속(B)에는 그 로그인이 전혀 보이지 않음 (§0-3-8)")
    finally:
        (auth.user_storage, auth.client_storage) = original


# =============================================================================
# [8] 🏢 매크로 방공망 (`web/pages/macro_page.py`) — 2026-08-17 (이전 6단계) 추가
#
#     이 화면은 로그인(사용자 자산)이 없는 **관리자 전용** 화면이라 [3]/[5]와 검사 항목이
#     다릅니다. 여기서 지켜야 할 것은 두 가지입니다.
#       ① 관리자가 아닌 접속에는 **본문이 한 글자도 그려지지 않는다** (§0-3-6 / §0-3-9)
#       ② 이식하면서 **숫자가 달라지지 않았다** — 오너가 "개발 중단"을 지시한 화면이라
#          기능 추가·개선이 아니라 "있는 그대로 옮기기"가 목표였기 때문입니다.
#          원본 `views/macro_view.py` 와 리터럴·차트 데이터를 직접 대조하던 검사는
#          2026-08-29 Streamlit 은퇴(views/ → archive/streamlit_views/)로 제거했습니다.
# =============================================================================
def test_macro_page_wiring():
    print("\n[8] web/pages/macro_page.py 배선 (🏢 매크로 방공망 · 관리자 전용)")
    _install_nicegui_stub()

    page_path = REPO_ROOT / "web" / "pages" / "macro_page.py"
    src = page_path.read_text(encoding="utf-8")
    code = python_code_only(src)

    # ── (a) 관리자 게이트 ────────────────────────────────────────────────
    # 2026-08-21 — 데코레이터에 `response_timeout=` 이 붙어서(비동기 페이지의 기본 3초 제한이
    # 영어 500 페이지를 띄우는 것을 막기 위함) 닫는 괄호까지 문자로 맞추지 않습니다.
    # 이 검사가 보려는 것은 **경로**이지 데코레이터 인자 구성이 아닙니다.
    check("@ui.page('/admin/macro'" in code, "경로가 /admin/macro (관리자 전용 네임스페이스)")
    check("if not is_admin():" in code and "render_admin_login()" in code,
          "페이지 첫 부분에서 is_admin() 확인 후 게이트 폼만 그림")
    check("def render_admin_login" not in code,
          "게이트 폼을 이 파일에 복붙하지 않고 admin_page 의 함수를 재사용 (§0-3-10)")
    check(("/admin/macro", "🏢 매크로 방공망 (관리자 전용)", True)
          in __import__("web.layout", fromlist=["_MENU"])._MENU,
          "드로어 메뉴에 등록되어 있고 admin_only=True (비관리자에게는 안 보임)")
    check("macro_page" in (REPO_ROOT / "main.py").read_text(encoding="utf-8"),
          "main.py 가 macro_page 를 import (@ui.page 등록)")

    # ── (c) 옛 프록시 계산식이 되살아나지 않았는가 (test_macro_scoring [15] 과 같은 기준) ──
    for var in ("skew_base", "synth_base"):
        pattern = re.compile(rf"^\s*{var}\s*=|clip\({var}\b", re.MULTILINE)
        check(not pattern.search(code), f"macro_page.py 에 '{var}' 계산/사용이 없음")
    check('"VKOSPI_Skew": None,' in code and '"Synthetic_Futures": None,' in code,
          "미리보기 분기는 두 지표를 산출 불가(None)로 두고 프록시로 채우지 않음 (§0-1)")
    check("0.5 + 0.3 * (usd_close - 1200) / 300" in code and "0.5 - 0.4 * kospi_change" in code,
          "살아있는 프록시 2개의 산식은 원본과 글자 그대로 같음")
    check("2500" not in code and "1350" not in code.replace("#", ""),
          "가짜 기본 시세(2500 / 1350)를 다시 넣지 않음 (§0-1)")

    # ── (d) utils/db.py 가 streamlit 에서 풀려났는가 (계획서 §4-2 6번 행) ──
    #
    #  ⚠️ 2026-08-17 예외 1건: `_notify()` 안에 **지연 import + try/except** 로 감싼
    #     streamlit 폴백이 있습니다. 콜백 없이 불렸을 때(NiceGUI 는 콜백을 항상 넘기므로
    #     해당 없음) 아직 살아있는 `views/macro_view.py`(듀얼런, 콜백을 안 넘김)가 실패
    #     배너를 잃어버리는 §0-1 회귀를 막기 위한 하위호환 장치입니다. 그래서 여기서는
    #     "streamlit 이 아예 없다"가 아니라 "① 모듈 최상위(하드 의존)에는 없고,
    #     ② `_notify()` 함수 밖 어디에도 없다"를 확인합니다 — 폴백 범위가 그 함수
    #     하나로 봉인돼 있는지가 핵심입니다.
    db_src = (REPO_ROOT / "utils" / "db.py").read_text(encoding="utf-8")
    db_tree = ast.parse(db_src)
    check(not any(
              isinstance(n, ast.Import) and any(a.name == "streamlit" for a in n.names)
              for n in module_level_statements(db_tree)
          ),
          "utils/db.py 최상위(모듈 스코프)에 streamlit import 가 없음 (하드 의존 아님)")

    notify_node = next(n for n in ast.walk(db_tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "_notify")
    notify_src = ast.get_source_segment(db_src, notify_node) or ""
    outside_notify = db_src.replace(notify_src, "")
    outside_notify = python_code_only(outside_notify)
    check("import streamlit" not in outside_notify,
          "streamlit import 가 _notify() 함수 밖 어디에도 없음 (폴백 범위 봉인)")
    check("st.session_state" not in outside_notify and "st.warning(" not in outside_notify
          and "st.write(" not in outside_notify and "st.error(" not in outside_notify,
          "utils/db.py 의 _notify() 밖에는 st.* 호출이 하나도 없음 (7곳 전부 콜백/로거로 전환)")
    notify_code_only = python_code_only(notify_src)
    check("get_script_run_ctx() is not None" in notify_code_only,
          "_notify() 의 streamlit 폴백은 실제 Streamlit 스크립트 실행 중일 때만 동작 "
          "(NiceGUI 요청에는 해당 없음)")
    check(notify_code_only.count("except") >= 1 and "try:" in notify_code_only,
          "_notify() 의 streamlit 폴백은 try/except 로 감싸져 미설치·비실행 환경에서도 안전")
    ai_code = python_code_only((REPO_ROOT / "utils" / "macro_ai.py").read_text(encoding="utf-8"))
    check("streamlit" not in ai_code, "utils/macro_ai.py 에 streamlit 의존이 없음")
    check("on_error=on_error" in code and "is_admin=is_admin_call" in code,
          "macro_page 가 저장 실패를 화면까지 전달할 콜백을 넘김 (§0-1 — 로그만 남기지 않음)")

    # ── (e) XSS / 예외 노출 (§0-3-9 · §0-3-4) ────────────────────────────
    check("esc(ai_comments_data.get(" in code,
          "AI 코멘트(외부 생성 텍스트)를 HTML 로 넣기 전에 esc() 를 거침 (§0-3-9)")
    # 예외 원문(`{e}` / `{exc}`)이 f-string 에 들어가는 줄은 **전부 print() 여야** 합니다.
    # (= 서버 로그로만 나감. 배너·notify 문구에 섞이면 §0-3-4 위반)
    leaky = [line.strip() for line in code.splitlines()
             if ("{e}" in line or "{exc}" in line) and "print(" not in line]
    check(not leaky, "예외 원문이 서버 로그(print)에만 쓰이고 화면 문구에는 없음 (§0-3-4)",
          f"발견: {leaky}")

    # ── (f) 차트 — 같은 계열·같은 값인가 (계획서 §9 "6. macro" 완료기준 ③) ──
    check('px.line(chart_data.reset_index(), x="Date", y="위험 지수")' in code,
          "차트가 원본과 같은 호출 (계열 1개 = '위험 지수', x = Date)")
    check("h-80" not in code and "height: 300px" in code,
          "차트 높이를 명시 (안 주면 0px 로 그려져 통째로 사라짐 — 계획서 §7)")


def test_macro_render_smoke():
    print("\n[8-b] 매크로 화면 렌더 스모크 (실제 market_history.csv)")
    _install_nicegui_stub()
    from nicegui import app
    import web.pages.macro_page as macro

    # (1) 비관리자는 본문이 **한 글자도** 그려지지 않아야 합니다.
    seen = []
    original = (macro._render_dashboard, macro.render_admin_login, macro.is_admin)

    # 🔴 2026-08-30 재감사(테스트 스위트) S-1 추가 발견 — 이 기기엔 실제 nicegui가 설치돼
    # 있어(`_install_nicegui_stub()`가 스텁 없이 그대로 통과) `app.storage.user`가 진짜
    # `nicegui.storage.Storage` 객체입니다. 진짜 요청(request) 컨텍스트 밖에서는 이게
    # `is_script_mode_preflight()` 상태에 따라 RuntimeError를 던지거나(요청 없음 +
    # storage_secret 없음), 혹은 매번 새로 만들어지는 `PseudoPersistentDict()`를 돌려줍니다
    # — 후자면 여기서 `["admin"] = True`로 쓴 값이 `macro_page()` 내부의 `is_admin()`
    # 호출(별도 PseudoPersistentDict 인스턴스)에는 전혀 보이지 않아, 관리자로 설정했는데도
    # 게이트를 통과 못 하는 것처럼 조용히 실패합니다(재현: `pytest -k test_macro_render_smoke`
    # 단독 실행 시 RuntimeError, 전체 파일과 함께 실행 시 이 check() 실패 — 둘 다 같은
    # 근본 원인의 다른 증상). `macro_page.py`가 `web.auth.is_admin`을 이름으로 import해서
    # 쓰므로(`from web.auth import is_admin`), 진짜 저장소를 흉내내는 대신 §0-3-8 원칙
    # ("관리자 여부는 전역 추측이 아니라 명시적으로 받는다") 그대로 `macro.is_admin`
    # 자체를 갈아 끼웁니다 — 이 화면이 실제로 의존하는 것은 저장소가 아니라
    # `is_admin()`의 반환값 하나뿐입니다.
    #
    # 2026-08-21 — `macro_page()`/`_render_dashboard()` 가 `async def` 가 되었습니다
    # (AI 코멘트 파일을 `run.io_bound` 로 읽게 한 수정). 그래서 가짜 본문도 **코루틴을
    # 돌려주는 함수**여야 `await _render_dashboard()` 가 성립합니다.
    async def _fake_dashboard():
        seen.append("body")

    macro._render_dashboard = _fake_dashboard
    macro.render_admin_login = lambda: seen.append("login")
    try:
        macro.is_admin = lambda: False
        run_render(macro.macro_page())
        check(seen == ["login"], "🔒 비관리자 접속 → 게이트 폼만, 본문 렌더 0회")
        seen.clear()
        macro.is_admin = lambda: True
        run_render(macro.macro_page())
        check(seen == ["body"], "🔓 관리자 접속 → 본문 렌더")
    finally:
        (macro._render_dashboard, macro.render_admin_login, macro.is_admin) = original

    # (2) 본문 전체를 실제로 실행 — f-string·이스케이프·분기가 전부 진짜로 돕니다.
    app.storage.user["admin"] = True
    try:
        run_render(macro._render_dashboard())
        check(True, "본문 전체 렌더 (탭 7개·표·차트·다운로드 버튼 포함) 예외 0건")
    except Exception as exc:                       # noqa: BLE001
        check(False, "본문 전체 렌더", f"({type(exc).__name__}: {exc})")

    # (3) §0-1 회귀 — 이력 파일이 없으면 숫자를 한 개도 그리지 않아야 합니다.
    drawn = []
    saved = (macro._html, macro.error_banner, macro.warning_banner,
             macro.info_banner, macro.success_banner, macro.banner, macro.HISTORY_FILE)
    macro._html = lambda markup: drawn.append(markup)
    macro.error_banner = lambda text: drawn.append(("error", text))
    macro.warning_banner = lambda text: drawn.append(text)
    macro.info_banner = lambda text: drawn.append(text)
    macro.success_banner = lambda text: drawn.append(text)
    macro.banner = lambda kind, body: drawn.append(body)
    macro.HISTORY_FILE = str(REPO_ROOT / "__no_such_market_history__.csv")
    try:
        run_render(macro._render_dashboard())
        blob = "\n".join(str(d) for d in drawn)
        check(any(isinstance(d, tuple) and d[0] == "error" for d in drawn),
              "🚨 이력 파일이 없으면 빨간 실패 배너가 뜸 (§0-1)")
        check("RISK INDEX" not in blob and "apartment-building" not in blob,
              "그 상태에서 위험 지수·층 카드를 그리지 않음 (가짜 수치 렌더 금지)")
        check("Traceback" not in blob, "화면에 트레이스백이 없음 (§0-3-4)")
    finally:
        (macro._html, macro.error_banner, macro.warning_banner,
         macro.info_banner, macro.success_banner, macro.banner, macro.HISTORY_FILE) = saved
        app.storage.user.clear()

    # (4) 🔐 §0-3-9 — AI 코멘트(외부 생성 텍스트)가 HTML 로 새지 않는지 실제 값으로 확인
    import json
    import tempfile
    app.storage.user["admin"] = True
    tmp_path = Path(tempfile.mkdtemp()) / "macro_commentary.json"
    tmp_path.write_text(json.dumps({
        "comments": {"FX_Swap_Point": "<img src=x onerror=alert(1)>달러 유동성 주의"},
        "comment_dates": {"FX_Swap_Point": "2026-01-01"},
    }, ensure_ascii=False), encoding="utf-8")
    captured = []
    saved = (macro._html, macro.data_path, macro.warning_banner)
    macro._html = lambda markup: captured.append(markup)
    macro.data_path = lambda name: str(tmp_path)
    macro.warning_banner = lambda text: captured.append(text)
    try:
        result = macro.fetch_verified_market_data()
        run_render(macro._render_ai_commentary(result[4], result[3]))
        blob = "\n".join(captured)
        check("<img src=x onerror" not in blob, "🔐 AI 코멘트의 <img onerror=...> 가 그대로 나가지 않음")
        check("&lt;img src=x onerror" in blob, "   → 이스케이프된 문자열로 표시됨 (글자 그대로 보임)")
        check("달러 유동성 주의" in blob, "   → 정상 문장은 그대로 보존됨")
        check("2026-01-01 생성 코멘트" in blob, "오늘 것이 아닌 코멘트는 생성일자를 함께 표기 (§0-1)")
    finally:
        (macro._html, macro.data_path, macro.warning_banner) = saved
        app.storage.user.clear()


# =============================================================================
# [9] ⚔️ 결투다! (`web/pages/duel_page.py`) — 2026-08-20 추가 (작업지시서 2단계 화면)
#
#     이 화면은 '내 성적표'·'사장님 보고서'에 이은 **세 번째 로그인 필요 화면**이고,
#     여기서 처음으로 앱이 사용자 대신 상태를 바꿉니다(주문 저장·수정·취소). 그래서
#     [3]/[5] 와 같은 기준(client·user_id 를 인자로, 전역 추측 금지, esc, 예외 원문 금지)에
#     더해 이 모듈 고유의 두 가지를 함께 고정합니다.
#       ① **3단계 공개 게이트**(작업지시서 2-8) — 플래그가 꺼져 있으면 URL 로 들어와도
#          본문이 그려지지 않고, 관리자 전용 단계에서는 관리자에게만 그려집니다.
#       ② **규칙을 화면에서 다시 구현하지 않았는지** — 체결·시간대·수익률은 전부
#          `utils/duel_rules.py` / `utils/duel_db.py` 호출이어야 합니다(§0-3-10).
# =============================================================================
def test_duel_page_wiring():
    print("\n[9] web/pages/duel_page.py 배선 (⚔️ 결투다! · 로그인 필요 · 3단계 공개)")
    path = REPO_ROOT / "web" / "pages" / "duel_page.py"
    check(path.exists(), "web/pages/duel_page.py 존재")
    if not path.exists():
        return
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # "이 낱말이 코드에 없는지"를 볼 때는 **주석·독스트링을 걷어낸** 문자열로 확인합니다
    # ([5] 와 같은 이유 — 이 파일도 왜 그렇게 했는지를 주석으로 길게 설명합니다).
    code = python_code_only(src)

    # ── (a) DB를 만지는 함수는 client·user_id 를 **인자로** 받는다 (§0-3-8 함수 설계 원칙) ──
    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("_render_body", "_render_duel_section", "_render_opt_in", "_render_accounts",
                 "_render_account_card", "_render_order_form", "_render_orders_section",
                 "_render_account_orders"):
        node = funcs.get(name)
        args = [a.arg for a in node.args.args] if node else []
        check(node is not None and "client" in args and "user_id" in args,
              f"`{name}()` 이 client·user_id 를 인자로 받음", f"실제 인자: {args}")

    # ── (b) DB 호출에 client 가 첫 인자로 들어가는지 (전역에서 추측하지 않는지) ──
    for call_name in ("fetch_my_accounts", "fetch_my_positions", "fetch_my_cash_ledger",
                      "fetch_my_orders", "fetch_my_snapshots",
                      "save_order", "edit_order", "cancel_order", "opt_in"):
        calls = _calls_with_client_first_arg(tree, call_name)
        check(bool(calls),
              f"`{call_name}(client, …)` — 클라이언트를 명시적으로 넘김 (직접 또는 run_blocking 경유)",
              f"호출 {len(calls)}건")

    # ── (c) 🔴 opt_in() 은 **인자가 클라이언트 하나뿐**이어야 합니다 ──
    #    대상자는 앱이 정하지 않고 DB 안에서 auth.uid() 로만 정해집니다(스키마 §9-10).
    #    화면이 user_id 를 끼워 넣으려는 시도 자체가 생기지 않도록 여기서 고정합니다.
    #    🔴 2026-08-21 — `run_blocking(opt_in, client)` 로 감싼 호출도 인정합니다(위 (b)와
    #    같은 이유). 다만 "인자가 client 하나뿐"이라는 조건은 감싼 형태에서도 그대로
    #    지켜야 하므로 `run_blocking(opt_in, client)`(길이 2, 키워드 없음)만 인정합니다.
    opt_in_direct = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                     and n.func.id == "opt_in"
                     and len(n.args) == 1 and not n.keywords]
    opt_in_wrapped = [n for n in ast.walk(tree)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                      and n.func.id == "run_blocking"
                      and len(n.args) == 2 and not n.keywords
                      and isinstance(n.args[0], ast.Name) and n.args[0].id == "opt_in"
                      and isinstance(n.args[1], ast.Name) and n.args[1].id == "client"]
    check(bool(opt_in_direct or opt_in_wrapped),
          "`opt_in(client)` — 사용자 id·금액·날짜를 넘기는 경로가 없음 (auth.uid() 로만 결정, "
          "직접 또는 run_blocking 경유)")

    # ── (d) 🔒 소유자 이중 확인 — RLS 가 지워져도 남의 행을 그리지 않음 ──
    check('account.get("user_id") != user_id' in code,
          "계좌를 그리기 전에 account['user_id'] == user_id 를 한 번 더 확인 (§0-3-8 이중 방어)")

    # ── (e) 저장소 직접 접근 금지 · Streamlit 잔재 없음 ──
    check(bool(re.search(r'from nicegui import[^\n]*\bui\b', src)) and "app.storage" not in code,
          "화면 파일은 app.storage 를 직접 만지지 않음 (web/auth.py 경유)")
    check("import streamlit" not in code and "st.session_state" not in code,
          "Streamlit 코드가 섞여 있지 않음")

    # ── (f) 로그인 경로 공유 — 다른 두 화면과 **같은 세션·같은 폼** ──
    check("has_supabase_session" in code and "from web.auth import" in code,
          "로그인 여부를 web/auth.py 로 판단 (scorecard·report 와 같은 세션)")
    check("from web.auth_ui import" in code and "render_auth()" in code,
          "로그인 폼을 web/auth_ui.py 공용 함수로 그림 (§0-3-10)")
    for forbidden in ("sign_in(", "sign_up(", "SESSION_USER_KEY", "set_session("):
        check(forbidden not in code,
              f"자체 로그인 처리(`{forbidden}`)를 따로 만들지 않음 — 인증 경로는 web/auth.py 하나")

    # ── (g) 🚧 3단계 공개 게이트 (작업지시서 2-8 · 7단계) ──
    # 2026-08-21 — `@ui.page('/admin/macro'` 와 같은 이유로 닫는 괄호를 뺐습니다(response_timeout).
    check("@ui.page('/duel'" in code, "경로가 /duel")
    check("if not DUEL_ENABLED:" in code,
          "플래그가 꺼져 있으면 URL 로 직접 들어와도 본문을 그리지 않음 (§0-3-6 기본 숨김)")
    check("DUEL_MENU_ADMIN_ONLY and not is_admin()" in code,
          "관리자 전용 단계에서는 관리자가 아닌 접속에 본문을 그리지 않음 (메뉴 숨김만으로는 부족)")
    check("from web.layout import" in code and "DUEL_ENABLED" in code,
          "공개 스위치를 화면이 따로 만들지 않고 web/layout.py 의 상수 하나를 같이 봄 (§0-3-10)")

    # ── (h) 규칙을 화면에서 다시 구현하지 않았는지 (§0-3-10) ──
    check("duel_rules.resolve_order_window(" in code,
          "주문 접수 시간대 판정을 duel_rules 에 위임 (화면이 두 번째 정의를 만들지 않음)")
    check("duel_rules.compute_twr(" in code,
          "누적 수익률(TWR)을 duel_rules.compute_twr() 으로 계산 (화면에 계산식 없음)")
    check("ORDER_WINDOW_OPEN_TIME" in code and '"18:00' not in code and "'18:00" not in code,
          "접수 시각을 화면에 직접 적지 않고 규칙 상수에서 만들어 씀")
    check("resolve_stock_query" in code and "build_universe_index" in code,
          "종목 검색·유니버스 목록을 기존 함수로 재사용 (두 번째 로더를 만들지 않음)")
    # 🔁 2026-08-21 — 여기 있던 검사("매도 경로('sell')가 화면 어디에도 없음 — 이 모듈에
    #    매도는 없습니다")를 **뒤집었습니다.** "매도 영원히 없음"이라는 결정 자체가 이전
    #    라운드의 대화 착오였음이 오너 확인으로 드러나 정정됐고, 이제 계좌마다 30/90/180일
    #    주기로 **딱 1회씩 리밸런싱 매도**가 가능합니다(규칙 계층 §12 · DB 부분 유니크 인덱스
    #    `duel_orders_one_sell_per_window`). 낡은 검사를 그대로 두면 사실과 반대인 것을
    #    회귀로 고정하게 되므로, 같은 자리에서 **매도 저장 경로가 실제로 있는지**를 봅니다.
    check("save_sell_order" in code,
          "리밸런싱 매도 저장 경로가 화면에 있음 (창당 1회 — 2026-08-21 오너 정정)")
    check("resolve_rebalance_window" in code,
          "리밸런싱 창 판정을 duel_rules 에 위임 (화면이 창 길이를 다시 세지 않음)")

    # ── (i) 상시 노출 고지 3종 (작업지시서 2-8) ──
    check("배당금은 반영되지 않습니다" in src, "고지 ① 배당 미반영")
    check("주문은 저장 즉시 체결되지 않습니다" in src, "고지 ② 즉시 체결 아님")
    # 🔁 2026-08-21 — 고지 ③ 의 내용이 "매수 전용"에서 "매수 + 창당 1회 리밸런싱 매도"로
    #    바뀌었습니다(위와 같은 정정). 고지의 자리와 개수는 그대로이고 사실만 바뀝니다.
    #    ⚠️ "옛 문구가 없는지"만 `code`(주석·독스트링 제거본)로 봅니다 — 화면 파일은 "왜
    #       그 문구를 버렸는지"를 주석으로 설명하고 있어서, 원문으로 검사하면 그 설명 자체에
    #       걸려 항상 실패합니다(아래 (j) 의 '그날 밤에 체결' 검사와 같은 이유).
    #    🗣️ 2026-08-22 오너 리뷰 — 같은 사실을 "창"이 아니라 **"매도 기회"**를 주어로 세워
    #       다시 썼습니다("'창'보다도 '매도 기회'라고 하는게 직관적으로 이해될 것 같아").
    #       사실은 그대로이고 낱말만 바뀌었으므로 검사도 새 문장으로 옮깁니다.
    check("매수는 언제든, 매도 기회는 주기마다 딱 한 번입니다" in src
          and "매도는 지원하지 않습니다" not in code,
          "고지 ③ 매수 + 주기당 1회 리밸런싱 매도 기회 (옛 '매도 없음' 문구가 남아 있지 않음)")
    check("MANDATORY_NOTICES" in code and "for notice in MANDATORY_NOTICES" in code,
          "세 고지를 한 곳에 모아 화면 상단에 **항상** 그림 (조건 분기 뒤에 숨지 않음)")

    # ── (j) 🔴 체결 시점 문구가 확정된 시간 모델(2-4)과 일치하는지 ──
    #    작업지시서 2-8 초안에는 "그날 밤에 체결"이라고 적혀 있지만, 나중에 나온 2-4 가
    #    "체결은 D+1 종가"로 **전면 확정**했습니다. 초안 문구를 그대로 복사하면 화면이
    #    사실과 다른 말을 하게 되므로(§0-1), 그 문장이 되살아나지 않게 고정합니다.
    # ⚠️ 여기서만 `src` 가 아니라 `code`(주석·독스트링 제거본)를 봅니다 — 이 화면 파일은
    #    "초안 문구를 왜 안 쓰는지"를 주석으로 설명하고 있어서, 원문으로 검사하면 그 설명
    #    자체에 걸려 항상 실패합니다([5] 의 같은 이유).
    check("그날 밤에 체결" not in code,
          "폐기된 초안 문구('그날 밤에 체결')가 사용자에게 보이는 문자열에 없음 "
          "— 확정 모델은 D+1 종가 체결 (2-4)")
    check("다음 거래일" in src, "체결 시점을 '다음 거래일 종가'로 안내")

    # ── (k) 사전 고지 — 수집 실패 시 주문 취소 (2-4-5: 사후 통보로 끝내지 않기) ──
    check("NOTICE_CRAWL_FAILURE" in code and "ui.checkbox(" in code,
          "주문 전에 '수집 실패 시 취소' 안내 + 확인 체크 영역이 있음 (2-4-5)")

    # ── (l) §0-1 — 계산 불가를 0% 로 채우지 않는지 ──
    check("TWR_INSUFFICIENT" in code and "아직 계산할 수 없음" in src,
          "TWR 이 계산 불가일 때 0% 가 아니라 '아직 계산할 수 없음'으로 표시 (§0-1)")
    check("가격 확인 중" in src,
          "가격을 못 구한 보유 종목을 0원으로 처리하지 않고 '가격 확인 중'으로 표시 (3-2)")

    # ── (m) XSS · 예외 원문 노출 (§0-3-9 / §0-3-4) ──
    check("esc(" in src, "HTML 출력에 esc() 사용")
    check("_fail(" in src and "traceback" not in src,
          "예상 못 한 예외는 화면에 원문을 흘리지 않고 로그로만 보냄 (§0-3-4)")

    # ── (n) 메뉴 배선 — 기본은 숨김, 켜면 관리자 전용부터 ──
    import web.layout as layout_module
    check(all(item[0] != "/duel" for item in layout_module._MENU),
          "DUEL_ENABLED 가 꺼진 기본 상태에서는 메뉴에 /duel 항목이 아예 없음 (1단계 전체 숨김)",
          f"실제 메뉴: {[i[0] for i in layout_module._MENU]}")
    menu_when_on, admin_only_flag = _menu_with_duel_enabled()
    entries = [item for item in menu_when_on if item[0] == "/duel"]
    check(len(entries) == 1,
          "DUEL_ENABLED=true 면 메뉴에 /duel 항목이 정확히 하나 생김 (2단계)",
          f"실제: {entries}")
    check(bool(entries) and entries[0][2] is admin_only_flag,
          "그 항목의 관리자전용 플래그가 DUEL_MENU_ADMIN_ONLY 와 같은 값 "
          "(3단계 전환 = 이 불리언 하나만 False 로)",
          f"실제: {entries}")
    # ✅ 오너 확정 (2026-08-22) — 2단계(관리자 전용) → 3단계(전체 공개)로 전환.
    # 리밸런싱 매도 라운드 + 성적표 카드 가격 버그까지 검수를 마친 뒤 오너가 직접
    # 확정한 전환입니다(web/layout.py 의 DUEL_MENU_ADMIN_ONLY 주석 참고). 이전엔
    # 여기서 `admin_only_flag is True` 를 확인했었습니다 — 이력은 지우지 않고
    # 값만 뒤집어 남겨둡니다.
    check(admin_only_flag is False,
          "지금은 3단계(전체 공개) 설정 — 관리자 로그인 없이도 /duel 메뉴가 보임",
          f"실제 DUEL_MENU_ADMIN_ONLY={admin_only_flag}")

    # ── (o) main.py 등록 ──
    main_path = REPO_ROOT / "main.py"
    if main_path.exists():
        check("duel_page" in main_path.read_text(encoding="utf-8"),
              "main.py 가 duel_page 를 import (@ui.page 등록)")
    else:                                          # pragma: no cover - 저장소에는 항상 있음
        check(False, "main.py 존재", "← 이 스냅샷에는 main.py 가 없습니다")


def _menu_with_duel_enabled():
    """`DUEL_ENABLED=true` 로 `web/layout.py` 를 다시 읽어 그때의 메뉴를 돌려줍니다.

    플래그는 import 시점에 환경변수로 한 번 판정되므로, "켰을 때 어떤 모양인가"를 확인하려면
    모듈을 다시 읽는 수밖에 없습니다. 끝나면 **반드시 원래 상태로 되돌립니다** — 이 뒤의
    검사들이 "기본값(꺼짐)" 을 전제로 하기 때문입니다.
    """
    import importlib
    import web.layout as layout_module

    saved = os.environ.get("DUEL_ENABLED")
    os.environ["DUEL_ENABLED"] = "true"
    try:
        reloaded = importlib.reload(layout_module)
        return list(reloaded._MENU), reloaded.DUEL_MENU_ADMIN_ONLY
    finally:
        if saved is None:
            os.environ.pop("DUEL_ENABLED", None)
        else:
            os.environ["DUEL_ENABLED"] = saved
        importlib.reload(layout_module)


# =============================================================================
# [9-b] ⚔️ 결투 화면 렌더 스모크 — 로그인 후 본문을 **실제로 실행**해봅니다
# =============================================================================
#  [4]/[6] 과 같은 방식입니다. 위젯은 스텁이라 화면이 그려지진 않지만, 금액 서식·HTML
#  이스케이프·TWR 계산·부분체결 문구·통화 표기는 전부 진짜로 실행됩니다.
#  ⚠️ 계좌·주문·현금은 **합성 데이터**이고 DB 호출은 전부 대체합니다(§0-1 — 실제 Supabase 에
#     접속하지 않고, 실데이터를 지어내지도 않습니다). 시세만 저장소의 실제 스냅샷을 읽습니다.
# =============================================================================
DUEL_SYNTHETIC_ACCOUNTS = [
    {"id": "acc-m1", "user_id": "uid-duel", "window_type": "M1", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
    {"id": "acc-m3", "user_id": "uid-duel", "window_type": "M3", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
    {"id": "acc-m6", "user_id": "uid-duel", "window_type": "M6", "seed_amount": 10000000,
     "currency": "KRW", "anchor_date": "2026-08-03", "status": "active"},
]

DUEL_SYNTHETIC_LEDGER = [
    {"id": 1, "account_id": "acc-m1", "event_type": "seed", "amount": 10000000,
     "event_date": "2026-08-03"},
    {"id": 2, "account_id": "acc-m1", "event_type": "monthly_deposit", "amount": 800000,
     "event_date": "2026-08-10"},
    {"id": 3, "account_id": "acc-m1", "event_type": "buy", "amount": -700000,
     "event_date": "2026-08-11"},
]

DUEL_SYNTHETIC_POSITIONS = [
    {"id": "pos-1", "account_id": "acc-m1", "ticker": "005930", "stock_name": "삼성전자",
     "quantity": 10, "avg_cost": 70000, "status": "active", "delisted_date": None},
    # 🔐 종목명에 스크립트를 심어 둔 행 — 화면에 **글자 그대로** 나와야 합니다 (§0-3-9).
    #    (유니버스 밖 코드라 가격도 못 구합니다 → "가격 확인 중" 경로도 같이 탑니다.)
    {"id": "pos-2", "account_id": "acc-m1", "ticker": "999999",
     "stock_name": "<img src=x onerror=alert(1)>", "quantity": 3, "avg_cost": 1000,
     "status": "active", "delisted_date": None},
]

DUEL_SYNTHETIC_ORDERS = [
    {"id": "ord-1", "account_id": "acc-m1", "ticker": "005930", "stock_name": "삼성전자",
     "requested_quantity": 10, "status": "pending", "saved_at": "2026-08-19T19:00:00+09:00",
     "target_date": "2026-08-20"},
    {"id": "ord-2", "account_id": "acc-m1", "ticker": "000660", "stock_name": "SK하이닉스",
     "requested_quantity": 10, "status": "partially_filled", "filled_quantity": 7,
     "filled_price": 100000, "filled_amount": 700000, "filled_date": "2026-08-11",
     "saved_at": "2026-08-10T19:00:00+09:00", "target_date": "2026-08-11",
     "fail_reason": "요청 10주 중 7주만 예수금 부족으로 체결"},
]

DUEL_SYNTHETIC_SNAPSHOTS = [
    {"snapshot_date": "2026-08-03", "account_id": "acc-m1", "position_value": 0,
     "cash_balance": 10000000, "total_value": 10000000, "total_cost": 0,
     "cash_flow_amount": 10000000, "cash_flow_kind": "seed", "priced_count": 0,
     "unpriced_count": 0},
    {"snapshot_date": "2026-08-10", "account_id": "acc-m1", "position_value": 0,
     "cash_balance": 10800000, "total_value": 10800000, "total_cost": 0,
     "cash_flow_amount": 800000, "cash_flow_kind": "monthly_deposit", "priced_count": 0,
     "unpriced_count": 0},
    {"snapshot_date": "2026-08-11", "account_id": "acc-m1", "position_value": 740000,
     "cash_balance": 10100000, "total_value": 10840000, "total_cost": 700000,
     "cash_flow_amount": 0, "cash_flow_kind": None, "priced_count": 1, "unpriced_count": 0},
]


def test_duel_render_smoke():
    print("\n[9-b] 결투 화면 렌더 스모크 (합성 계좌·주문·현금)")
    _install_nicegui_stub()
    import web.pages.duel_page as page

    captured_html = []
    import web.components.widgets as widgets
    from nicegui import ui

    original = (page.fetch_my_accounts, page.fetch_my_cash_ledger, page.fetch_my_positions,
                page.fetch_my_orders, page.fetch_my_snapshots)
    original_html = ui.html

    def _for_account(rows):
        return lambda client, account_id: [
            dict(r) for r in rows if r.get("account_id") == account_id
        ]

    page.fetch_my_accounts = lambda client, user_id: [dict(a) for a in DUEL_SYNTHETIC_ACCOUNTS]
    page.fetch_my_cash_ledger = _for_account(DUEL_SYNTHETIC_LEDGER)
    page.fetch_my_positions = _for_account(DUEL_SYNTHETIC_POSITIONS)
    page.fetch_my_orders = _for_account(DUEL_SYNTHETIC_ORDERS)
    page.fetch_my_snapshots = (
        lambda client, account_id, start_date=None, end_date=None:
        [dict(r) for r in DUEL_SYNTHETIC_SNAPSHOTS if r.get("account_id") == account_id]
    )

    def _capture_html(content='', *a, **k):
        captured_html.append(str(content))
        return original_html(content, *a, **k)

    ui.html = _capture_html
    widgets.ui.html = _capture_html
    try:
        # 2026-08-21 — `_render_body()` 가 `async def` 입니다(코스피 유니버스 스냅샷을
        # `run.io_bound` 로 읽게 한 수정). 부르는 방법만 바뀌고 검사 내용은 그대로입니다.
        run_render(page._render_body(object(), "uid-duel", "duel@example.com"))
        check(True, "_render_body() 가 예외 없이 끝까지 실행됨")
    except Exception as exc:                       # noqa: BLE001
        check(False, "_render_body() 가 예외 없이 끝까지 실행됨", f"({type(exc).__name__}: {exc})")
    finally:
        (page.fetch_my_accounts, page.fetch_my_cash_ledger, page.fetch_my_positions,
         page.fetch_my_orders, page.fetch_my_snapshots) = original
        ui.html = original_html
        widgets.ui.html = original_html

    blob = "\n".join(captured_html)
    check(bool(blob), "렌더 중 HTML 이 실제로 만들어짐", f"(조각 {len(captured_html)}개)")
    check("<img src=x onerror=" not in blob,
          "🔐 종목명에 심어둔 <img onerror=...> 가 HTML 로 살아나오지 않음 (§0-3-9 XSS)")
    check("&lt;img src=x onerror=alert(1)&gt;" in blob,
          "🔐 그 문자열이 이스케이프되어 '글자 그대로' 출력됨")
    check("가격 확인 중" in blob,
          "가격을 못 구한 종목은 0원이 아니라 '가격 확인 중' 으로 표시 (§0-1 / 3-2)")
    check("요청 10주 중 7주만" in blob,
          "부분체결은 요청 수량과 실제 체결 수량을 둘 다 보여줌 (1-3 / 2-4-6)")

    # 🔴 §0-1 회귀 — 남의 계좌가 섞여 오면 **아무것도 그리지 않아야** 합니다.
    drawn = []
    saved_banner = page.error_banner
    page.error_banner = lambda text: drawn.append(text)
    page.fetch_my_accounts = lambda client, user_id: [
        dict(DUEL_SYNTHETIC_ACCOUNTS[0], user_id="uid-someone-else"),
    ]
    try:
        # 🔴 2026-08-21 발견 — `_render_duel_section()` 이 (달러 트랙 추가로) `async def` 가
        # 되면서 이 줄이 그동안 코루틴 객체만 만들고 **한 번도 실행하지 않았습니다**
        # (pytest 가 "코루틴이 await 되지 않았다" 경고만 내고 조용히 넘어감 — 그래서 아래
        # check() 가 항상 실패였는데도 이 파일의 check()/FAILURES 버그 뒤에 숨어 있었습니다).
        # 직접 `run_render()`으로 실행해 실제 §0-3-8 이중 방어 코드를 진짜로 태웁니다.
        run_render(page._render_duel_section(object(), "uid-duel",
                                  run_render(page._load_kospi_universe()),
                                  page._order_window_state(), lambda: None))
        blob2 = "\n".join(str(d) for d in drawn)
        check(bool(drawn) and "본인 것이 아닌" in blob2,
              "🔒 남의 user_id 가 섞인 계좌 목록은 그리지 않고 오류로 알림 (§0-3-8)")
    except Exception as exc:                       # noqa: BLE001
        check(False, "🔒 남의 계좌 혼입 방어 경로 실행", f"({type(exc).__name__}: {exc})")
    finally:
        page.error_banner = saved_banner
        page.fetch_my_accounts = original[0]


# =============================================================================
# [0] 🌐 데이터 원격 로드가 **꺼져 있는 상태**임을 못 박습니다 (2026-08-17 추가)
# =============================================================================
#  `utils/data_source.py`(계획서 §8-5 B안)가 들어오면서 `web/state.py` 의 내부 구현이
#  바뀌었습니다. 아래 [4]/[6]/[8-b] 렌더 스모크가 **예전과 같은 조건(로컬 파일만)** 에서
#  돌았다는 것을 이 검사가 보증합니다. 원격이 켜진 채로 돌면 스모크의 의미가 달라집니다.
def test_data_source_defaults_to_local():
    print("\n[0] 🌐 데이터 원격 로드 기본값 = 꺼짐 (아래 렌더 스모크의 전제 조건)")
    import utils.data_source as ds
    import web.state as state

    check(not os.environ.get(ds.ENV_BASE_URL),
          f"이 테스트 프로세스에 {ds.ENV_BASE_URL} 가 설정돼 있지 않음",
          f"실제: {os.environ.get(ds.ENV_BASE_URL)!r}")
    check(ds.is_remote_enabled() is False, "원격 로더가 꺼진 상태로 판정됨")
    check(ds.get_staleness_status() is None, "전역 '최신 아님' 배너 상태가 없음")

    # 화면 5개가 부르는 함수의 **이름·인자·반환 계약**이 그대로인지 (호출부 무변경의 근거)
    import inspect
    check([p.name for p in inspect.signature(state.data_path).parameters.values()] == ["filename"],
          "web/state.data_path(filename) 시그니처 유지")
    check([p.name for p in inspect.signature(state.load_json_file).parameters.values()] == ["path"],
          "web/state.load_json_file(path) 시그니처 유지")
    check([p.name for p in inspect.signature(state.read_download_bytes).parameters.values()] == ["path"],
          "web/state.read_download_bytes(path) 시그니처 유지")

    real = state.data_path("kospi200_pegy_latest.json")
    payload, error = state.load_json_file(real)
    if os.path.exists(real):
        check(payload is not None and error is None,
              "실제 스냅샷을 로컬 파일에서 그대로 읽음(네트워크 없이)",
              f"({error})")
    else:                                              # pragma: no cover - 저장소에는 항상 있음
        check(payload is None and error is not None, "파일이 없으면 실패 사유를 그대로 돌려줌")

    # 전역 배너는 화면 5개가 아니라 공용 껍데기 한 곳에만 있어야 합니다 (§0-3-10)
    layout_src = (REPO_ROOT / "web" / "layout.py").read_text(encoding="utf-8")
    check("get_staleness_status" in layout_src, "web/layout.py 한 곳에서만 최신성 배너를 그림")
    duplicated = [rel(p) for p in (REPO_ROOT / "web" / "pages").glob("*.py")
                  if "get_staleness_status" in p.read_text(encoding="utf-8")]
    check(not duplicated, "화면 파일에는 같은 배너 코드가 복붙되지 않음", f"발견: {duplicated}")


def test_pages_import_cleanly():
    print("\n[3-b] 모듈 import 검증 (문법·배선 오류 조기 발견)")
    _install_nicegui_stub()
    for module_name in ("web.auth", "web.auth_ui", "web.layout",
                        "web.pages.admin_page", "web.pages.macro_page",
                        "web.pages.scorecard_page", "web.pages.report_page",
                        "web.pages.duel_page",
                        # 🟠 M16(2026-08-29) 추가 — 배당 화면 2개가 이 검증 대상에서
                        # 빠져 있었습니다(재감사 확인, grep 0건).
                        "web.pages.dividend_page", "web.pages.dividend_us_page"):
        try:
            __import__(module_name)
        except Exception as exc:                   # noqa: BLE001
            check(False, f"{module_name} import", f"({type(exc).__name__}: {exc})")
        else:
            check(True, f"{module_name} import")


def test_dividend_pages_use_esc_for_external_strings():
    """🔴 L12(2026-08-29) — `DIVIDEND_MODULE_WORK_ORDER.md` [항목 5]가 "화면 파일마다
    `esc(` 사용을 자동으로 강제 검사한다"고 적어 놨지만, 실제로는 그 검사가 스코어카드ㆍ
    리포트ㆍ결투 등 **이름을 하나하나 지정한 화면 파일에만** 걸려 있고 배당 화면 2개는
    빠져 있었습니다(재감사로 확인, 문서도 같이 정정함). 문서 정정만으로 끝내지 않고, 이
    화면 2개에 대해서만이라도 같은 검사를 실제로 걸어 둡니다 — "esc() 를 쓰고 있다는
    사실을 사람이 코드를 읽어서만 아는" 상태를 "테스트가 지켜주는" 상태로 바꿉니다.

    ⚠️ 이 검사는 "esc( 라는 글자가 파일에 있는가"만 봅니다(다른 화면 파일들의 (d) 검사와
    같은 얕은 방식) — 실제로 모든 외부 문자열이 빠짐없이 esc()를 거치는지까지는 보장하지
    않습니다. 그래도 "esc() 를 아예 안 쓰는 새 화면"이 조용히 들어오는 것은 막습니다.
    """
    print("\n[3-c] 배당 화면 esc() 사용 검사 (L12)")
    for module_name in ("dividend_page", "dividend_us_page"):
        src = (REPO_ROOT / "web" / "pages" / f"{module_name}.py").read_text(encoding="utf-8")
        check("esc(" in src, f"web/pages/{module_name}.py 가 esc() 를 사용함")


# =============================================================================
# [10] 🚪 `@ui.page` **진입점 함수 자체** 렌더 스모크 — 2026-08-30 추가
#
#  🔴 왜 이 절이 생겼는가 (사각지대의 정체)
#     위 [4]/[6]/[9-b] 는 전부 **안쪽 헬퍼**만 직접 불렀습니다 —
#       · [4]  `scorecard_page._render_body(...)`
#       · [6]  `report_page._render_report_body(...)`
#       · [9-b] `duel_page._render_body(...)` / `_render_duel_section(...)`
#     즉 `@ui.page` 가 붙은 **진짜 진입점**(`scorecard_page()` · `report_page()` ·
#     `duel_page()`)의 몸통 — 공개 플래그 게이트, Supabase 준비 확인, 로그인 게이트,
#     세션 만료 처리, 본문 호출을 감싼 try/except — 은 지금까지 **한 줄도 실행된 적이
#     없었습니다**. [8-b] 매크로만 유일하게 `run_render(macro.macro_page())` 로 진입점
#     자체를 돌리고 있었고, 이 절은 그 패턴을 나머지 화면 전부로 넓힌 것입니다.
#
#     이 저장소는 실제로 이 사각지대 때문에 사고를 겪었습니다 —
#     TASK_HISTORY_ARCHIVE.md `#128`/`#129`: CSS f-string 안 중괄호 하나가 빠져서 배포
#     직후 전 화면이 `UnboundLocalError` 로 죽었는데, 로컬 테스트는 전부 초록불이었습니다.
#     화면 함수 안의 오타·참조 오류는 **그 함수를 실제로 실행해봐야만** 잡힙니다.
#
#  ⚠️ 로그인이 필요한 화면 5개(scorecard/report/duel/consent/leaderboard)의 진입점은
#     본문 호출을 `try: ... except Exception: error_banner(...)` 로 감싸고 있습니다.
#     그래서 "예외가 안 났다"만 보면 **본문이 통째로 터져도 초록불**이 됩니다
#     (§0-1 — 실패를 정상 상태로 위장). 그 catch-all 이 쓰는 **폴백 문구를 그대로**
#     감시해서, 배너로 삼켜진 실패까지 테스트 실패가 되게 합니다.
#
#  ⚠️ 이 절이 확인하는 것은 "끝까지 예외 없이 그려지는가" 하나입니다. 화면 **내용**의
#     정확성(금액 서식·XSS 이스케이프·계산 결과)은 [4]/[6]/[9-b] 가 이미 안쪽 헬퍼를
#     직접 불러서 훨씬 촘촘하게 보고 있습니다 — 여기서 그걸 다시 검사하지 않습니다
#     (§0-3-10 같은 검증을 두 번 만들지 않기).
# =============================================================================

#: 진입점의 catch-all 이 화면에 그리는 **폴백 문구**들. 이 중 하나라도 배너로 나왔다면
#: 본문 어딘가에서 예외가 났는데 진입점이 그걸 삼킨 것입니다(§0-1).
_ENTRY_SWALLOWED_MARKERS = (
    "화면을 그리는 중 문제가 발생했습니다",
    "순위표를 그리는 중 문제가 발생했습니다",
    "로그인 상태를 확인하지 못했습니다",
)


class _EntryFakeClient:
    """진입점이 `get_client_async()` 로 받는 객체 자리.

    아무 일도 하지 않습니다 — DB 조회 함수는 전부 아래에서 합성 데이터로 대체하므로
    이 객체의 메서드는 한 번도 불리지 않습니다(§0-1 — 실제 Supabase 에 접속하지 않고,
    실데이터를 지어내지도 않습니다).
    """


def _entry_run(page, coro_factory, label):
    """진입점을 **실제로 실행**하고, 그 함수의 catch-all 이 삼킨 실패까지 잡아냅니다.

    :returns: 렌더 도중 `error_banner()` 로 그려진 문자열 목록.
    """
    drawn = []
    original = getattr(page, "error_banner", None)
    if original is not None:
        page.error_banner = lambda text: drawn.append(str(text))
    try:
        run_render(coro_factory())
        check(True, f"{label} 가 예외 없이 끝까지 실행됨")
    except Exception as exc:                       # noqa: BLE001
        check(False, f"{label} 가 예외 없이 끝까지 실행됨", f"({type(exc).__name__}: {exc})")
    finally:
        if original is not None:
            page.error_banner = original

    blob = "\n".join(drawn)
    swallowed = [m for m in _ENTRY_SWALLOWED_MARKERS if m in blob]
    check(not swallowed,
          f"{label} — 진입점의 catch-all 배너가 뜨지 않음(본문이 조용히 실패하지 않음)",
          f"(배너: {blob[:400]})")
    return drawn


def _entry_supabase_ready(page):
    """`supabase_status()` 를 '준비됨'으로 바꿉니다.

    테스트 프로세스에는 Supabase 접속 정보가 없으므로 진입점이 맨 앞의 "준비중" 안내에서
    그냥 끝나 버립니다 — 그러면 정작 검증하려는 로그인 게이트 아래쪽이 한 줄도 안 돕니다.
    **원래 값을 돌려주니 호출부는 반드시 finally 에서 되돌립니다.**
    """
    from utils.scorecard_db import SupabaseStatus
    original = page.supabase_status
    page.supabase_status = lambda: SupabaseStatus(
        available=True, reason="", package_available=True, config_present=True)
    return original


def _entry_open_session(page, user=None):
    """진입점의 로그인 게이트를 '정상 로그인' 상태로 통과시킵니다.

    저장소(`app.storage.*`)를 흉내내지 않고 **화면이 실제로 부르는 함수 3개**를 갈아
    끼웁니다 — [8-b] 매크로 스모크가 `macro.is_admin` 하나만 바꾼 것과 같은 판단입니다
    (진짜 요청 컨텍스트 밖에서는 `app.storage.user` 가 매번 다른 사전이라 값을 넣어도
    화면 쪽에는 보이지 않습니다). 되돌릴 원래 값 4개를 튜플로 돌려줍니다.
    """
    saved = (page.supabase_status, page.has_supabase_session,
             page.get_client_async, page.current_user_async)
    who = dict(user or {"id": "uid-entry-test", "email": "entry@example.com"})

    async def _client():
        return _EntryFakeClient()

    async def _user(_client_arg):
        return dict(who)

    _entry_supabase_ready(page)
    page.has_supabase_session = lambda: True
    page.get_client_async = _client
    page.current_user_async = _user
    return saved


def _entry_restore_session(page, saved):
    (page.supabase_status, page.has_supabase_session,
     page.get_client_async, page.current_user_async) = saved


def test_admin_page_entrypoint_render_smoke():
    """🚪 `/admin` — 이 저장소에서 **유일한 동기 화면 함수**의 진입점 스모크."""
    print("\n[10-a] /admin 진입점 렌더 스모크 (관리자 게이트 양쪽)")
    _install_nicegui_stub()
    import web.pages.admin_page as page

    # `admin_page()` 는 `async def` 가 아닙니다 — 데이터·네트워크를 전혀 쓰지 않아
    # `tests/test_event_loop_blocking.py` 의 `NO_IO_PAGES` 예외로 등록된 유일한 화면입니다.
    # `run_render()` 는 코루틴을 받으므로 얇은 async 껍데기 하나로 감싸서 **다른 화면과
    # 똑같은 슬롯 컨텍스트**에서 돌립니다(§0-3-10 — 실행 방법을 새로 만들지 않습니다).
    async def _call():
        page.admin_page()

    seen = []
    saved = (page.is_admin, page.render_admin_login, page._render_console)
    try:
        page.render_admin_login = lambda: seen.append("login")
        page._render_console = lambda: seen.append("console")

        page.is_admin = lambda: False
        _entry_run(page, _call, "admin_page() (비관리자)")
        check(seen == ["login"], "🔒 비관리자 → 비밀번호 폼만, 관리자 콘솔 렌더 0회",
              f"실제: {seen}")

        seen.clear()
        page.is_admin = lambda: True
        _entry_run(page, _call, "admin_page() (관리자)")
        check(seen == ["console"], "🔓 관리자 → 관리자 콘솔 렌더", f"실제: {seen}")
    finally:
        (page.is_admin, page.render_admin_login, page._render_console) = saved

    # 대체 없이 **진짜 폼·진짜 콘솔**까지 전부 실행합니다 — f-string·분기·파일 존재 확인이
    # 여기서 처음으로 진짜로 돕니다(#128/#129 부류의 오타를 잡는 자리).
    saved_is_admin = page.is_admin
    try:
        page.is_admin = lambda: False
        _entry_run(page, _call, "admin_page() 본문 전체 (비관리자 · 실제 로그인 폼)")
        page.is_admin = lambda: True
        _entry_run(page, _call, "admin_page() 본문 전체 (관리자 · 실제 콘솔)")
    finally:
        page.is_admin = saved_is_admin


def test_privacy_page_entrypoint_render_smoke():
    """🚪 `/privacy` — 로그인·플래그가 전혀 없는 상시 공개 화면."""
    print("\n[10-b] /privacy 진입점 렌더 스모크")
    _install_nicegui_stub()
    import web.pages.privacy_page as page

    _entry_run(page, lambda: page.privacy_page(), "privacy_page()")
    # 본문이 통째로 f-string 상수라, 그 상수가 실제로 완성되는지(#128/#129 부류)까지가
    # 이 화면에서 확인할 수 있는 전부입니다.
    check(page.CONTACT_EMAIL in page._BODY_MARKDOWN,
          "본문 f-string 이 문의처 이메일까지 정상적으로 조립됨")


def test_scorecard_page_entrypoint_render_smoke():
    """🚪 `/scorecard` — [4] 가 건너뛴 **진입점 몸통**(로그인 게이트 포함)."""
    print("\n[10-c] /scorecard 진입점 렌더 스모크 (로그인 게이트 양쪽)")
    _install_nicegui_stub()
    import web.pages.scorecard_page as page

    # ── ① 비로그인 — 로그인 폼만 그리고 본문은 한 번도 안 불려야 합니다 ──────
    seen = []
    saved_status = _entry_supabase_ready(page)
    saved = (page.has_supabase_session, page.render_auth, page._render_body)
    try:
        page.has_supabase_session = lambda: False
        page.render_auth = lambda: seen.append("auth")

        async def _no_body(*_a, **_k):
            seen.append("body")

        page._render_body = _no_body
        _entry_run(page, lambda: page.scorecard_page(), "scorecard_page() (비로그인)")
        check(seen == ["auth"], "🔒 비로그인 → 로그인 폼만, 본문 렌더 0회", f"실제: {seen}")
    finally:
        (page.has_supabase_session, page.render_auth, page._render_body) = saved
        page.supabase_status = saved_status

    # ── ② 정상 로그인 — 게이트를 지나 **본문 전체**까지 진짜로 그립니다 ──────
    saved_session = _entry_open_session(page)
    saved_fetch = page.fetch_holdings
    page.fetch_holdings = lambda client, user_id: [dict(h) for h in SYNTHETIC_HOLDINGS]
    try:
        _entry_run(page, lambda: page.scorecard_page(),
                   "scorecard_page() (정상 로그인 · 합성 보유종목)")
    finally:
        page.fetch_holdings = saved_fetch
        _entry_restore_session(page, saved_session)


def test_report_page_entrypoint_render_smoke():
    """🚪 `/report` — [6] 이 건너뛴 **진입점 몸통**(로그인 게이트 포함)."""
    print("\n[10-d] /report 진입점 렌더 스모크 (로그인 게이트 양쪽)")
    _install_nicegui_stub()
    import web.pages.report_page as page

    # ── ① 비로그인 ────────────────────────────────────────────────────────
    seen = []
    saved_status = _entry_supabase_ready(page)
    saved = (page.has_supabase_session, page.render_auth, page._render_signed_in)
    try:
        page.has_supabase_session = lambda: False
        page.render_auth = lambda: seen.append("auth")

        async def _no_body(*_a, **_k):
            seen.append("body")

        page._render_signed_in = _no_body
        _entry_run(page, lambda: page.report_page(), "report_page() (비로그인)")
        check(seen == ["auth"], "🔒 비로그인 → 로그인 폼만, 본문 렌더 0회", f"실제: {seen}")
    finally:
        (page.has_supabase_session, page.render_auth, page._render_signed_in) = saved
        page.supabase_status = saved_status

    # ── ② 정상 로그인 — [6] 과 **같은 합성 스냅샷**을 같은 정규화를 거쳐 넣습니다 ──
    from utils.report_db import sort_holding_snapshots, sort_snapshots
    saved_session = _entry_open_session(page)
    saved_fetch = (page.fetch_user_snapshots, page.fetch_user_holding_snapshots)
    page.fetch_user_snapshots = \
        lambda client, user_id, **kw: sort_snapshots(SYNTHETIC_SNAPSHOTS)
    page.fetch_user_holding_snapshots = \
        lambda client, user_id, **kw: sort_holding_snapshots(SYNTHETIC_HOLDING_SNAPSHOTS)
    try:
        _entry_run(page, lambda: page.report_page(),
                   "report_page() (정상 로그인 · 합성 스냅샷)")
    finally:
        (page.fetch_user_snapshots, page.fetch_user_holding_snapshots) = saved_fetch
        _entry_restore_session(page, saved_session)


def test_duel_page_entrypoint_render_smoke():
    """🚪 `/duel` — [9-b] 가 건너뛴 **진입점 몸통**(3단계 공개 게이트 + 로그인 게이트)."""
    print("\n[10-e] /duel 진입점 렌더 스모크 (공개 게이트 · 로그인 게이트)")
    _install_nicegui_stub()
    import web.pages.duel_page as page

    saved_flags = (page.DUEL_ENABLED, page.DUEL_MENU_ADMIN_ONLY)
    try:
        # ── ① 플래그 꺼짐(1단계 전체 숨김) → "준비중" 안내만, 본문 0회 ──────
        seen = []
        saved = (page._render_coming_soon, page._render_header, page._render_body)
        try:
            page.DUEL_ENABLED = False
            page._render_coming_soon = lambda: seen.append("soon")
            page._render_header = lambda: seen.append("header")

            async def _no_body(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body
            _entry_run(page, lambda: page.duel_page(), "duel_page() (플래그 꺼짐)")
            check(seen == ["soon"], "🚧 플래그가 꺼져 있으면 URL 로 들어와도 준비중 안내만",
                  f"실제: {seen}")
        finally:
            (page._render_coming_soon, page._render_header, page._render_body) = saved

        # ── ② 플래그 켜짐 + 비로그인 → 로그인 폼만 ─────────────────────────
        seen = []
        page.DUEL_ENABLED = True
        page.DUEL_MENU_ADMIN_ONLY = False
        saved_status = _entry_supabase_ready(page)
        saved = (page.has_supabase_session, page.render_auth, page._render_body)
        try:
            page.has_supabase_session = lambda: False
            page.render_auth = lambda: seen.append("auth")

            async def _no_body2(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body2
            _entry_run(page, lambda: page.duel_page(), "duel_page() (플래그 켜짐 · 비로그인)")
            check(seen == ["auth"], "🔒 비로그인 → 로그인 폼만, 본문 렌더 0회", f"실제: {seen}")
        finally:
            (page.has_supabase_session, page.render_auth, page._render_body) = saved
            page.supabase_status = saved_status

        # ── ③ 플래그 켜짐 + 정상 로그인 → [9-b] 와 같은 합성 계좌로 본문 전체 ──
        saved_session = _entry_open_session(page, {"id": "uid-duel", "email": "duel@example.com"})
        saved_krw = (page.fetch_my_accounts, page.fetch_my_cash_ledger, page.fetch_my_positions,
                     page.fetch_my_orders, page.fetch_my_snapshots)
        saved_usd = (page.fetch_my_accounts_usd, page.fetch_my_cash_ledger_usd,
                     page.fetch_my_positions_usd, page.fetch_my_orders_usd,
                     page.fetch_my_snapshots_usd)

        def _for_account(rows):
            return lambda client, account_id: [
                dict(r) for r in rows if r.get("account_id") == account_id
            ]

        page.fetch_my_accounts = lambda client, user_id: [dict(a) for a in DUEL_SYNTHETIC_ACCOUNTS]
        page.fetch_my_cash_ledger = _for_account(DUEL_SYNTHETIC_LEDGER)
        page.fetch_my_positions = _for_account(DUEL_SYNTHETIC_POSITIONS)
        page.fetch_my_orders = _for_account(DUEL_SYNTHETIC_ORDERS)
        page.fetch_my_snapshots = (
            lambda client, account_id, start_date=None, end_date=None:
            [dict(r) for r in DUEL_SYNTHETIC_SNAPSHOTS if r.get("account_id") == account_id]
        )
        # 💵 달러 트랙은 **계좌 0개**(참여 안 함)로 둡니다 — 원화만 참여한 사용자가 실제로
        #    존재하는 정상 상태이고(모듈 머리말 6번), 그 경로도 진입점을 통해 돌아 봅니다.
        page.fetch_my_accounts_usd = lambda client, user_id: []
        page.fetch_my_cash_ledger_usd = lambda client, account_id: []
        page.fetch_my_positions_usd = lambda client, account_id: []
        page.fetch_my_orders_usd = lambda client, account_id: []
        page.fetch_my_snapshots_usd = (
            lambda client, account_id, start_date=None, end_date=None: []
        )
        try:
            _entry_run(page, lambda: page.duel_page(),
                       "duel_page() (플래그 켜짐 · 정상 로그인 · 합성 계좌)")
        finally:
            (page.fetch_my_accounts, page.fetch_my_cash_ledger, page.fetch_my_positions,
             page.fetch_my_orders, page.fetch_my_snapshots) = saved_krw
            (page.fetch_my_accounts_usd, page.fetch_my_cash_ledger_usd,
             page.fetch_my_positions_usd, page.fetch_my_orders_usd,
             page.fetch_my_snapshots_usd) = saved_usd
            _entry_restore_session(page, saved_session)
    finally:
        (page.DUEL_ENABLED, page.DUEL_MENU_ADMIN_ONLY) = saved_flags


def test_scorecard_consent_page_entrypoint_render_smoke():
    """🚪 `/scorecard/consent` — 지금까지 **어떤 테스트도 실행해 본 적 없는** 화면."""
    print("\n[10-f] /scorecard/consent 진입점 렌더 스모크")
    _install_nicegui_stub()
    import web.pages.scorecard_consent_page as page

    saved_flags = (page.SCORECARD_CONSENT_ENABLED, page.SCORECARD_CONSENT_MENU_ADMIN_ONLY)
    try:
        # ── ① 플래그 꺼짐 → 준비중 안내만 ─────────────────────────────────
        seen = []
        saved = (page._render_coming_soon, page._render_header, page._render_body)
        try:
            page.SCORECARD_CONSENT_ENABLED = False
            page._render_coming_soon = lambda: seen.append("soon")
            page._render_header = lambda: seen.append("header")

            async def _no_body(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body
            _entry_run(page, lambda: page.scorecard_consent_page(),
                       "scorecard_consent_page() (플래그 꺼짐)")
            check(seen == ["soon"], "🚧 플래그가 꺼져 있으면 준비중 안내만", f"실제: {seen}")
        finally:
            (page._render_coming_soon, page._render_header, page._render_body) = saved

        page.SCORECARD_CONSENT_ENABLED = True
        page.SCORECARD_CONSENT_MENU_ADMIN_ONLY = False

        # ── ② 비로그인 → 로그인 폼만 ──────────────────────────────────────
        seen = []
        saved_status = _entry_supabase_ready(page)
        saved = (page.has_supabase_session, page.render_auth, page._render_body)
        try:
            page.has_supabase_session = lambda: False
            page.render_auth = lambda: seen.append("auth")

            async def _no_body2(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body2
            _entry_run(page, lambda: page.scorecard_consent_page(),
                       "scorecard_consent_page() (비로그인)")
            check(seen == ["auth"], "🔒 비로그인 → 로그인 폼만, 본문 렌더 0회", f"실제: {seen}")
        finally:
            (page.has_supabase_session, page.render_auth, page._render_body) = saved
            page.supabase_status = saved_status

        # ── ③ 정상 로그인 → 본문 전체 (동의 기록이 아직 없는 신규 사용자) ──
        saved_session = _entry_open_session(page)
        saved_fetch = (page.fetch_my_consent, page.fetch_my_nickname)
        page.fetch_my_consent = lambda client, user_id: None
        page.fetch_my_nickname = lambda client, user_id: None
        try:
            _entry_run(page, lambda: page.scorecard_consent_page(),
                       "scorecard_consent_page() (정상 로그인 · 동의 기록 없음)")
        finally:
            (page.fetch_my_consent, page.fetch_my_nickname) = saved_fetch
            _entry_restore_session(page, saved_session)
    finally:
        (page.SCORECARD_CONSENT_ENABLED, page.SCORECARD_CONSENT_MENU_ADMIN_ONLY) = saved_flags


def test_scorecard_leaderboard_page_entrypoint_render_smoke():
    """🚪 `/scorecard/leaderboard` — 지금까지 **어떤 테스트도 실행해 본 적 없는** 화면."""
    print("\n[10-g] /scorecard/leaderboard 진입점 렌더 스모크")
    _install_nicegui_stub()
    import web.pages.scorecard_leaderboard_page as page

    saved_flags = (page.SCORECARD_LEADERBOARD_ENABLED,
                   page.SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY)
    try:
        # ── ① 플래그 꺼짐 → 준비중 안내만 ─────────────────────────────────
        seen = []
        saved = (page._render_coming_soon, page._render_fixed_notice, page._render_body)
        try:
            page.SCORECARD_LEADERBOARD_ENABLED = False
            page._render_coming_soon = lambda: seen.append("soon")
            page._render_fixed_notice = lambda: seen.append("notice")

            async def _no_body(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body
            _entry_run(page, lambda: page.scorecard_leaderboard_page(),
                       "scorecard_leaderboard_page() (플래그 꺼짐)")
            check(seen == ["soon"], "🚧 플래그가 꺼져 있으면 준비중 안내만", f"실제: {seen}")
        finally:
            (page._render_coming_soon, page._render_fixed_notice, page._render_body) = saved

        page.SCORECARD_LEADERBOARD_ENABLED = True
        page.SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY = False

        # ── ② 비로그인 → 로그인 폼만 ──────────────────────────────────────
        seen = []
        saved_status = _entry_supabase_ready(page)
        saved = (page.has_supabase_session, page.render_auth, page._render_body)
        try:
            page.has_supabase_session = lambda: False
            page.render_auth = lambda: seen.append("auth")

            async def _no_body2(*_a, **_k):
                seen.append("body")

            page._render_body = _no_body2
            _entry_run(page, lambda: page.scorecard_leaderboard_page(),
                       "scorecard_leaderboard_page() (비로그인)")
            check(seen == ["auth"], "🔒 비로그인 → 로그인 폼만, 본문 렌더 0회", f"실제: {seen}")
        finally:
            (page.has_supabase_session, page.render_auth, page._render_body) = saved
            page.supabase_status = saved_status

        # ── ③ 정상 로그인 → 본문 전체 (발행된 순위표가 없는 그룹 = 정상 상태) ──
        #    ⚠️ "발행된 순위표가 있는" 경로는 발행표 행 모양을 지어내야 해서 여기서는
        #       다루지 않습니다(§0-1 — 모양을 추측해 만든 가짜 행으로 초록불을 만들지
        #       않습니다). 진입점 몸통·게이트·선택 위젯·그룹 조회까지는 전부 실행됩니다.
        saved_session = _entry_open_session(page)
        saved_fetch = page.fetch_public_leaderboard_latest_date
        page.fetch_public_leaderboard_latest_date = (
            lambda client, currency=None, bracket_key=None: None
        )
        try:
            _entry_run(page, lambda: page.scorecard_leaderboard_page(),
                       "scorecard_leaderboard_page() (정상 로그인 · 발행분 없음)")
        finally:
            page.fetch_public_leaderboard_latest_date = saved_fetch
            _entry_restore_session(page, saved_session)
    finally:
        (page.SCORECARD_LEADERBOARD_ENABLED,
         page.SCORECARD_LEADERBOARD_MENU_ADMIN_ONLY) = saved_flags


# =============================================================================
def main():
    print("=" * 74)
    print("🔴 동시 접속 세션 격리 검증 (ENGINEERING_SPEC.md §0-3-8 / 계획서 §9 완료기준 ⑦)")
    print("=" * 74)

    test_data_source_defaults_to_local()
    test_no_mutable_globals()
    test_user_named_globals_are_constants()
    test_no_global_rebinding()
    test_storage_access_is_centralised()
    test_two_sessions_do_not_mix()
    test_scorecard_page_wiring()
    test_render_smoke()
    test_report_page_wiring()
    test_report_render_smoke()
    test_report_period_navigation()
    test_login_is_shared_between_scorecard_and_report()
    test_macro_page_wiring()
    test_macro_render_smoke()
    test_duel_page_wiring()
    test_duel_render_smoke()
    test_pages_import_cleanly()
    test_dividend_pages_use_esc_for_external_strings()
    # [10] @ui.page 진입점 함수 자체 렌더 스모크 (2026-08-30 추가)
    test_admin_page_entrypoint_render_smoke()
    test_privacy_page_entrypoint_render_smoke()
    test_scorecard_page_entrypoint_render_smoke()
    test_report_page_entrypoint_render_smoke()
    test_duel_page_entrypoint_render_smoke()
    test_scorecard_consent_page_entrypoint_render_smoke()
    test_scorecard_leaderboard_page_entrypoint_render_smoke()

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"❌ 실패 {len(FAILURES)}건: {FAILURES}")
        print("   ⚠️ 이 테스트가 실패하는 동안 '내 성적표' 화면을 공개하면 안 됩니다 (§0-3-8).")
        sys.exit(1)
    print("✅ 전체 통과 — 두 접속의 저장소가 물리적으로 분리되어 있고, 서로를 읽지도 쓰지도 않습니다.")
    print("=" * 74)


if __name__ == "__main__":
    main()
