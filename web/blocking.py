"""
🔴 이벤트 루프를 막는 동기 호출을 **별도 스레드로 넘기는 단 하나의 창구**.

무슨 사고를 막는 파일인가 (2026-08-21 2차 — "연결이 끊겼습니다" 재발)
────────────────────────────────────────────────────────────────────────────
1차 수정(`web/state.load_json_file_async`)으로 **JSON 스냅샷 읽기**는 이벤트 루프 밖으로
나갔습니다. 그런데도 오너가 홈('/')에서 같은 끊김을 다시 겪었습니다. 홈 화면은 이제
블로킹 I/O 를 하지 않으므로, 루프를 붙잡은 것은 **그 순간 다른 사람이 보내고 있던 다른
요청**이었습니다. 남아 있던 자리는 크게 두 종류였습니다.

  ① **Supabase(postgrest/gotrue) 동기 호출** — `fetch_holdings`, `fetch_my_accounts`,
     `save_order`, `current_user`, `set_session` … 전부 내부에서 `httpx` 로 **동기 HTTP
     왕복**을 합니다. '내 성적표' 한 번 그릴 때 보유종목 1회, '결투다!'는 계좌 3개 ×
     (현금·포지션·스냅샷) = 최소 10회입니다. 한 사람이 그 화면을 여는 동안 **접속자
     전원**의 WebSocket 하트비트가 그만큼 멈춥니다.
  ② **원격 CSV 읽기** — `utils/stock_history.load_stock_history()`(홈·미국 화면의 종목
     검색창)와 `utils/report_db.load_kospi_close_history()`(보고서 벤치마크)가
     `utils/data_source.read_text()` 를 타고, 원격 모드에서는 `requests.get()` 입니다.

NiceGUI 는 **한 프로세스 · 한 이벤트 루프**가 모든 접속자를 처리합니다. 위 호출 한 줄이
루프를 붙잡고 있는 동안 서버는 다른 누구에게도 응답하지 못하고, 브라우저는 하트비트가
끊긴 것으로 보고 "연결이 끊겼습니다. 다시 연결 중…" 을 띄웁니다. **자기 화면이 느린 게
아니라 남의 요청이 나를 멈추는** 구조라, 증상이 늘 엉뚱한 화면에서 나타납니다.

왜 함수 하나로 모으는가
────────────────────────────────────────────────────────────────────────────
고쳐야 할 자리가 서른 곳이 넘습니다. 각 자리에 `await run.io_bound(...)` 를 손으로 적으면
아래 **취소 규약**(§0-1 과 직결)을 서른 번 복붙해야 하고, 한 곳이라도 빠지면 "실패했는데
빈 목록으로 보이는" 조용한 거짓말이 됩니다. 그래서 `web/auth.py` 가 저장소 접근을
`user_storage()`/`client_storage()` 두 함수로 모아둔 것과 **같은 이유**로, 블로킹 위임도
이 파일 하나를 거치게 합니다 (ENGINEERING_SPEC.md §0-3-10 중복 금지 + 감사 지점 단일화).

🔴 이 파일을 고치는 사람에게 — `fn` 안에서 절대 하지 말 것
────────────────────────────────────────────────────────────────────────────
`run_blocking()` 에 넘기는 함수는 **다른 스레드**에서 실행됩니다. 그 스레드에는 "지금
어느 접속인지"를 담은 NiceGUI 컨텍스트가 **없습니다**. 따라서 넘기는 함수 안에서는

    ❌ `app.storage.user` / `app.storage.client` (= `web/auth.user_storage()` /
       `client_storage()`)  ← 2026-08-17 "로그인이 안 된다" 사고의 원인 그 자체입니다
       (`web/auth.py::login()` 독스트링, NiceGUI GitHub Discussion #2228/#2801)
    ❌ `ui.*` 위젯 생성 (`ui.label`, `ui.notify`, `with ui.card()` …)  ← 슬롯 컨텍스트도
       같은 방식으로 스레드에 따라다니지 않습니다

를 **한 줄도** 쓰면 안 됩니다. 필요한 값은 **부르는 쪽에서 이벤트 루프 위에서 미리 읽어**
평범한 인자로 넘기세요(`web/auth.py::login()`/`get_client_async()` 가 하는 그대로:
토큰을 먼저 동기로 꺼내고, 네트워크 호출만 스레드로 보냅니다).

반대로 아래는 **안전합니다** — 지금 이 파일을 통과하는 것도 전부 이쪽입니다.
    ✅ `client` 객체를 인자로 받아 쓰는 Supabase 질의 (`fetch_holdings(client, user_id)` …)
    ✅ 파일 읽기 / `requests` 왕복 / `pandas` 파싱 (모든 접속자에게 동일한 읽기 전용 데이터)
"""

from typing import Any, Callable


class BlockingCallAborted(RuntimeError):
    """블로킹 호출이 **결과를 내지 못하고 중단**됐다는 뜻 (§0-1 — 빈 값으로 위장 금지).

    `nicegui.run.io_bound` 는 **요청이 취소되었거나 서버가 내려가는 중**일 때 결과 대신
    `None` 을 돌려줍니다(NiceGUI 3.x 의 잠정 규약 — `web/state.load_json_file_async()` 가
    같은 자리에서 같은 처리를 합니다).

    이걸 그냥 통과시키면 어떤 일이 벌어지는가:
      · `fetch_holdings(...)` 가 `None` 을 돌려주고 → 화면은 "보유 종목이 없습니다" 를 그립니다.
        **조회에 실패한 것**과 **정말 0건인 것**이 화면에서 같아집니다. 자산 화면에서 이건
        단순 버그가 아니라 사용자가 오해할 수 있는 거짓 정보입니다(§0-1 정면 위반).
    그래서 값을 지어내지 않고 예외로 올립니다. 화면 쪽 `except Exception` 은 이미
    "사람이 읽는 한국어 한 문장 + 서버 로그" 규약(§0-3-4)을 갖고 있으므로, 부르는 자리를
    한 줄도 바꾸지 않고 그대로 정직한 실패 배너가 나갑니다.
    """


def _boxed(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple:
    """결과를 **1칸짜리 튜플에 담아** 돌려줍니다 (스레드 안에서 실행되는 부분).

    ⚠️ 이 한 겹이 필요한 이유: `fn` 자신이 정상적으로 `None` 을 돌려주는 경우가 흔합니다
       (`current_user()` 는 미로그인 상태에서 `None`, `fetch_my_nickname()` 도 그렇습니다).
       상자에 담지 않으면 그 정상적인 `None` 과 위 "취소되었음"의 `None` 을 구별할 방법이
       없어집니다. 상자에 담으면 취소는 `None`, 정상은 항상 `(값,)` 이라 절대 헷갈리지
       않습니다.
    """
    return (fn(*args, **kwargs),)


async def run_blocking(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """동기(블로킹) 함수 **하나**를 별도 스레드에서 실행하고 그 반환값을 그대로 돌려줍니다.

    화면 코드는 `rows = fetch_holdings(client, user_id)` 를
    `rows = await run_blocking(fetch_holdings, client, user_id)` 로 바꾸기만 하면 됩니다.
    **반환값·예외 모두 원래 함수와 완전히 같습니다** — 바뀌는 것은 "어느 스레드에서
    도는가" 뿐입니다. (원래 함수가 `ScorecardError`/`DuelDbError` 를 던지면 그대로
    올라오므로, 기존 `except` 절을 한 줄도 손대지 않아도 됩니다.)

    :raises BlockingCallAborted: 요청 취소·서버 종료로 결과 자체를 받지 못한 경우.

    ⚠️ 위 모듈 독스트링의 금지사항(`app.storage.*` / `ui.*` 를 `fn` 안에서 쓰지 않기)을
       반드시 지키세요. 그 검사는 사람 눈이 아니라
       `tests/test_event_loop_blocking.py` 가 자동으로 합니다.
    """
    # ⚠️ nicegui 는 **함수 안에서** 임포트합니다. 이 모듈이 nicegui 없이도 임포트되는
    #    순수 모듈이어야 오프라인 테스트·배치 스크립트가 영향을 받지 않습니다
    #    (`web/state.load_json_file_async()` 와 같은 판단).
    from nicegui import run                       # noqa: PLC0415

    boxed = await run.io_bound(_boxed, fn, *args, **kwargs)
    if boxed is None:
        raise BlockingCallAborted(
            '요청이 중단되었습니다. 잠시 후 다시 시도해 주세요.'
        )
    return boxed[0]
