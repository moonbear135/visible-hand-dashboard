# tests/test_duel_publish.py
"""
⚔️ "결투다!" 5단계 — **공개 순위표 발행 인프라** 오프라인 검증
   (네트워크 불필요 · Supabase 접속 불필요 · `supabase` 패키지 설치 여부와 무관)

DUEL_MODULE_WORK_ORDER.md 4단계·5단계에 따라, 가짜 Supabase 클라이언트와 손으로 만든 값으로만
검증합니다. `tests/test_duel.py`(순수 규칙) · `tests/test_duel_db.py`(맞는 표에 맞는 조건으로
보내는가) · `tests/test_duel_batch.py`(1갈래 하루치 순서)에 이어지는 **네 번째 축**이고,
여기서 보는 것은 **"남에게 보여도 되는 것만 보여지는가"** 입니다.

파일을 따로 만든 이유는 `tests/test_duel_batch.py` 가 `tests/test_duel_db.py` 에서 갈라져
나온 것과 같습니다 — 관심사 하나가 한 파일. 게다가 이 파일이 지키는 것은 §0-3-8(이 프로젝트의
최상위 무예외 원칙)이라, **혼자 열어서 처음부터 끝까지 읽을 수 있는 크기**로 두는 편이
리뷰에 훨씬 낫습니다.

검증 대상
    ① 체급 경계 8개 — 특히 "이상 / 미만" 경계값 **그 자체**(1억원 정확히, 1억원 −1원 등)
    ② 시즌 고정 — 시즌 중엔 매입원가가 변해도 체급이 안 바뀌고, 해가 바뀌면 다시 매겨지는가
    ③ 닉네임 — 정체성에서 유도되지 **않는가**(인자가 없다는 구조적 증거 + 값 검사),
       그리고 unique 충돌 시 재시도·경합 처리
    ④ 동의 철회 — 3개월 재동의 차단, `revoked_at` 은 남고, 발행 기록은 **모든 날짜에서** 삭제
    ⑤ 최소 인원 500명 — 499 vs 500 경계, 그리고 인원이 줄어든 그룹의 과거 행 제거
    ⑥ 전량 재작성 — 같은 날 두 번 돌려도 그날 행이 중복되지 않는가
    ⑦ NULL 규율 — 값이 없을 때 `None` 이지 `0`·`""` 가 아닌가(§0-1)
    ⑧ 🔴 §0-3-2 — 계좌가 3개든 900개든 왕복 횟수가 그대로인가(회귀 고정)
    ⑨ 🔴 §0-3-8 AST 검사 — 새 A 절 함수가 배치 키를 건드리지 않고, 발행표에 쓰는 코드가
       B 절에만 있으며, 동의 없는 사용자의 `holdings` 를 읽는 경로가 없는가

실행: pytest tests/test_duel_publish.py -v
"""

import ast
import inspect
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
# 가짜 Supabase 클라이언트는 `tests/test_duel_db.py` 가 갖고 있습니다. 같은 걸 다시 짜면
# 두 스위트가 서로 다른 방식으로 Supabase 를 흉내내기 시작합니다(§0-3-10 — 흉내도 단일 출처로).
sys.path.append(str(Path(__file__).parent))

from test_duel_db import FakeClient  # noqa: E402
from utils import duel_db, duel_publish, duel_rules  # noqa: E402
from utils.duel_db import DuelDbError  # noqa: E402
from utils.duel_publish import DuelPublishError  # noqa: E402
from utils.duel_rules import KST, DuelRuleError  # noqa: E402

TODAY = date(2026, 8, 20)
SEASON = "2026-01-01"


# =============================================================================
# 1. 체급 경계 — work order 5-3 (오너가 준 8구간 원문 그대로)
# =============================================================================
#  경계는 전부 **[하한 이상, 상한 미만)** 입니다. 아래 표는 오너 원문("1억원 이상",
#  "6천만원 이상 ~ 1억원 미만", …)을 그대로 옮긴 것이고, 경계값 **그 자체**가 어느 쪽으로
#  가는지를 한 줄씩 못 박습니다 — 여기가 틀리면 딱 경계에 선 사람이 남의 체급에서 겨룹니다.
@pytest.mark.parametrize("amount,expected", [
    # 1구간 — 1억원 이상
    (100_000_000, "krw_100m_plus"),        # 경계값 그 자체는 **위쪽** 구간
    (999_999_999, "krw_100m_plus"),
    (100_000_001, "krw_100m_plus"),
    # 2구간 — 6천만원 이상 ~ 1억원 미만
    (99_999_999, "krw_60m_100m"),          # 1억원 바로 아래
    (60_000_000, "krw_60m_100m"),          # 경계값 그 자체
    # 3구간 — 3천만원 이상 ~ 6천만원 미만
    (59_999_999, "krw_30m_60m"),
    (30_000_000, "krw_30m_60m"),
    # 4구간 — 1천만원 이상 ~ 3천만원 미만
    (29_999_999, "krw_10m_30m"),
    (10_000_000, "krw_10m_30m"),
    # 5구간 — 500만원 이상 ~ 1천만원 미만
    (9_999_999, "krw_5m_10m"),
    (5_000_000, "krw_5m_10m"),
    # 6구간 — 300만원 이상 ~ 500만원 미만
    (4_999_999, "krw_3m_5m"),
    (3_000_000, "krw_3m_5m"),
    # 7구간 — 100만원 이상 ~ 300만원 미만
    (2_999_999, "krw_1m_3m"),
    (1_000_000, "krw_1m_3m"),
    # 8구간 — 100만원 미만
    (999_999, "krw_under_1m"),
    (0, "krw_under_1m"),
])
def test_bracket_boundaries_match_the_owners_eight_tiers(amount, expected):
    assert duel_rules.assign_bracket(amount) == expected


def test_bracket_tiers_have_no_gaps_and_no_overlaps():
    """
    8구간이 **빈틈도 겹침도 없이** 0원부터 위로 이어지는지. 표를 손으로 고칠 때
    한 줄만 잘못 적어도 어떤 금액이 어느 구간에도 안 들어가거나 두 군데에 들어갑니다.
    """
    tiers = duel_rules.BRACKET_TIERS
    assert len(tiers) == 8, "오너가 확정한 구간 수는 8개입니다(5-3)"
    assert tiers[-1][2] == 0, "가장 낮은 구간의 하한은 0 이어야 합니다(구멍 없이 아래로 닫힘)"
    assert tiers[0][3] is None, "가장 높은 구간은 위로 열려 있어야 합니다"
    # 위에서 아래로 내려오며 "이 구간의 하한 == 아래 구간의 상한" 이어야 합니다.
    for upper, lower in zip(tiers, tiers[1:]):
        assert upper[2] == lower[3], f"{upper[0]} 과 {lower[0]} 사이에 구멍/겹침이 있습니다"


def test_bracket_amounts_live_only_in_duel_rules():
    """
    🔴 §0-3-10 — 경계 숫자의 **단일 출처**. 8개 경계값이 다른 파일에 다시 적혀 있으면,
    둘 중 하나만 바뀌는 날 어떤 사용자가 자기 것이 아닌 체급에서 겨루게 됩니다.
    """
    numbers = {"100_000_000", "60_000_000", "30_000_000", "5_000_000", "3_000_000"}
    for name in ("duel_db.py", "duel_publish.py", "duel_batch.py"):
        code = _executable_source(name)
        for number in numbers:
            assert number not in code, f"{name} 에 체급 경계 숫자({number})가 다시 적혀 있습니다"


def test_bracket_refuses_unknown_amounts_instead_of_guessing():
    """모르는 값을 최하위 구간으로 떨어뜨리지 않습니다(§0-1)."""
    for bad in (None, -1, "많이", float("nan")):
        with pytest.raises(DuelRuleError):
            duel_rules.assign_bracket(bad)


def test_bracket_none_key_is_not_one_of_the_eight():
    """'구간 미적용'은 9번째 구간이 아니라 **구간이 없다는 표시**입니다(5-2-4)."""
    assert duel_rules.BRACKET_NONE_KEY not in [tier[0] for tier in duel_rules.BRACKET_TIERS]
    assert duel_rules.BRACKET_NONE_KEY in duel_rules.BRACKET_KEYS
    assert len(duel_rules.BRACKET_KEYS) == 9
    assert duel_rules.bracket_label(duel_rules.BRACKET_NONE_KEY) == "구간 미적용"


# =============================================================================
# 2. 시즌 고정 — work order 5-3 (4·5차 확정: "체급은 시즌 동안 고정", 시즌 = 1년)
# =============================================================================
def test_season_length_constant_is_twelve_months():
    """작업지시서가 이름까지 제안한 설정값(`duel_season_length_months = 12`)."""
    assert duel_rules.DUEL_SEASON_LENGTH_MONTHS == 12


@pytest.mark.parametrize("day,expected", [
    (date(2026, 1, 1), "2026-01-01"),      # 시즌 첫날
    (date(2026, 8, 20), "2026-01-01"),
    (date(2026, 12, 31), "2026-01-01"),    # 시즌 마지막 날
    (date(2027, 1, 1), "2027-01-01"),      # 다음 시즌 첫날
    (date(2025, 6, 30), "2025-01-01"),
])
def test_season_key_is_the_calendar_year_start(day, expected):
    assert duel_rules.season_key_for_date(day) == expected


def test_bracket_stays_fixed_mid_season_even_if_real_principal_changes():
    """
    🔴 5-3 의 핵심 규칙. 시즌 도중에 실제 매입원가합계가 **크게 늘어도** 체급은 그대로입니다.
    이 배치는 매일 밤 돌기 때문에, 이 규칙이 조용히 사라지기 가장 쉬운 자리입니다.
    """
    existing = {"season_key": "2026-01-01", "bracket_key": "krw_1m_3m"}   # 100만~300만
    # 오늘 계산해 보면 1억 이상(= 훨씬 무거운 체급)이 나오는 상황.
    fresh = duel_rules.assign_bracket(150_000_000)
    assert fresh == "krw_100m_plus"

    resolved = duel_rules.resolve_bracket_for_season(existing, fresh, date(2026, 12, 31))
    assert resolved["bracket_key"] == "krw_1m_3m", "시즌 중에는 기존 체급이 이겨야 합니다"
    assert resolved["source"] == "kept"
    assert resolved["needs_write"] is False, "유지되는 배정은 다시 쓰지 않습니다"


def test_bracket_is_recomputed_when_the_season_rolls_over():
    """해가 바뀌면(새 시즌) 그 시점의 매입원가합계로 **다시** 매깁니다(5-3, 5차 확정)."""
    existing = {"season_key": "2026-01-01", "bracket_key": "krw_1m_3m"}
    fresh = duel_rules.assign_bracket(150_000_000)

    resolved = duel_rules.resolve_bracket_for_season(existing, fresh, date(2027, 1, 1))
    assert resolved["season_key"] == "2027-01-01"
    assert resolved["bracket_key"] == "krw_100m_plus"
    assert resolved["source"] == "assigned"
    assert resolved["needs_write"] is True


def test_first_ever_assignment_is_written():
    resolved = duel_rules.resolve_bracket_for_season(None, "krw_30m_60m", TODAY)
    assert resolved == {"season_key": SEASON, "bracket_key": "krw_30m_60m",
                        "source": "assigned", "needs_write": True}


def test_corrupt_stored_bracket_is_not_silently_replaced():
    """저장된 체급 문자열이 이상하면 임의의 값으로 갈아치우지 않고 멈춥니다(§0-1)."""
    with pytest.raises(DuelRuleError):
        duel_rules.resolve_bracket_for_season(
            {"season_key": SEASON, "bracket_key": "체급없음"}, "krw_1m_3m", TODAY)


def test_bracket_assignments_are_inserted_never_updated():
    """
    🔴 "시즌 중 고정"이 앱의 조심성이 아니라 **구조**임을 고정합니다.
    이 함수는 insert 만 하고 upsert/update 를 쓰지 않습니다 — DB 도 배치에게 update 권한을
    주지 않았기 때문에(스키마 §9-9), 여기에 upsert 가 생기면 그날 배치가 실패합니다.
    """
    client = FakeClient()
    duel_db.insert_bracket_assignments(client, [
        {"account_id": "acc-1", "season_key": SEASON, "bracket_key": "krw_1m_3m"}])
    call = client.only_call(duel_db.BRACKET_ASSIGNMENTS_TABLE)
    assert call.op == "insert", "체급 배정은 insert 여야 합니다(upsert 는 기존 배정을 덮어씁니다)"

    source = (REPO_ROOT / "utils" / "duel_db.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "insert_bracket_assignments")
    body = ast.get_source_segment(source, node)
    assert ".upsert(" not in body and ".update(" not in body


def test_bracket_assignment_duplicate_is_absorbed_not_raised():
    """
    같은 시즌 배정이 이미 있으면(배치 두 번 실행·경합) 조용히 0을 돌려줍니다 —
    **기존 값이 이깁니다.** 이게 곧 "체급은 시즌 동안 고정"입니다.
    """
    client = FakeClient(responses={
        (duel_db.BRACKET_ASSIGNMENTS_TABLE, "insert"):
            Exception("duplicate key value violates unique constraint"),
    })
    assert duel_db.insert_bracket_assignments(client, [
        {"account_id": "acc-1", "season_key": SEASON, "bracket_key": "krw_1m_3m"}]) == 0


def test_unrelated_insert_errors_are_not_swallowed():
    client = FakeClient(responses={
        (duel_db.BRACKET_ASSIGNMENTS_TABLE, "insert"): Exception("connection reset"),
    })
    with pytest.raises(DuelDbError):
        duel_db.insert_bracket_assignments(client, [
            {"account_id": "acc-1", "season_key": SEASON, "bracket_key": "krw_1m_3m"}])


# =============================================================================
# 3. 무작위 닉네임 — work order 5-5 / 스키마 §6
# =============================================================================
def test_nickname_generator_takes_no_input_at_all():
    """
    🔴 **이 함수의 안전성 근거이자, 이 파일에서 가장 중요한 한 줄.**

    닉네임을 `user_id`·이메일·가입시각에서 유도하면(해시 포함), 알고리즘이 알려지는 순간
    "이 닉네임은 누구인가"를 역계산할 수 있습니다. 소스 코드는 공개 저장소에 있으므로
    알고리즘이 알려지는 것은 시간 문제입니다(§0-3-9).

    그래서 검사하는 것은 "우리가 조심해서 user_id 를 안 넣었는가"가 아니라
    **"넣을 문법 자체가 없는가"** 입니다 — 인자가 하나도 없어야 합니다.
    (`duel_db.opt_in()` 의 무인자 검사와 같은 종류의 구조적 방어입니다.)
    """
    assert list(inspect.signature(duel_rules.generate_nickname).parameters) == [], \
        "generate_nickname() 은 인자를 하나도 받으면 안 됩니다 — 받는 순간 역추적 입력이 생깁니다"


def test_nickname_is_not_derived_from_identity_by_any_hash_or_encoding():
    """
    같은 '정체성'으로 여러 번 만들어도 **매번 다른 값**이 나오는지.

    결정적 함수(해시·인코딩·시드 고정 난수)라면 같은 입력에 같은 출력이 나옵니다. 인자가
    없으니 "같은 입력"이라는 개념 자체가 없지만, 혹시 나중에 누가 함수 안에서 전역 상태
    (예: 계좌 id 를 모듈 변수로 넘겨 받는 식)를 읽도록 고쳐도 여기서 잡힙니다.
    """
    samples = [duel_rules.generate_nickname() for _ in range(200)]
    assert len(set(samples)) > 190, "같은 값이 반복해서 나옵니다 — 결정적 생성이 의심됩니다"

    # 흔한 인코딩·해시로 만들어진 값이 아닌지 눈에 보이는 형태로도 확인합니다.
    import base64
    import hashlib
    identity = "9f3a2c11-b8d4-4e7a-9c02-5ad61f0e7b3d"
    forbidden = {
        hashlib.md5(identity.encode()).hexdigest(),
        hashlib.sha1(identity.encode()).hexdigest(),
        hashlib.sha256(identity.encode()).hexdigest(),
        base64.b64encode(identity.encode()).decode(),
        identity.replace("-", ""),
    }
    for sample in samples:
        assert sample not in forbidden
        # 식별자 조각이 닉네임 안에 섞여 들어가지도 않아야 합니다.
        #  (4자리 무작위 숫자 접미사와 **우연히** 겹치는 것까지 실패로 세지 않도록,
        #   글자가 섞인 조각과 8자 이상 조각만 봅니다 — 유도 여부를 가리는 데는 충분합니다.)
        for chunk in identity.split("-"):
            if chunk.isdigit() and len(chunk) <= duel_rules.NICKNAME_NUMBER_DIGITS:
                continue
            assert chunk not in sample
        assert identity.replace("-", "") not in sample
        for digest in forbidden:
            assert digest[:8] not in sample


def test_nickname_shape_and_entropy():
    """
    닉네임은 (형용사 + 명사 + 숫자) 이고, 후보 공간이 **조용히 좁아지지 않는지** 고정합니다.
    단어 목록을 지우면 익명성이 그만큼 얇아집니다(같은 이름을 쓰는 사람이 늘어납니다).
    """
    assert duel_rules.NICKNAME_NUMBER_DIGITS >= 4
    assert len(duel_rules.NICKNAME_ADJECTIVES) >= 40
    assert len(duel_rules.NICKNAME_NOUNS) >= 40
    assert len(set(duel_rules.NICKNAME_ADJECTIVES)) == len(duel_rules.NICKNAME_ADJECTIVES)
    assert len(set(duel_rules.NICKNAME_NOUNS)) == len(duel_rules.NICKNAME_NOUNS)
    # 참가자 1만 명에서 충돌 확률이 1% 를 넘지 않을 만큼은 넓어야 합니다.
    assert duel_rules.nickname_space_size() >= 5_000_000

    sample = duel_rules.generate_nickname()
    assert sample[-duel_rules.NICKNAME_NUMBER_DIGITS:].isdigit()
    assert any(sample.startswith(word) for word in duel_rules.NICKNAME_ADJECTIVES)


def test_nickname_uses_a_cryptographic_random_source():
    """
    `random` 의 기본 난수가 아니라 `secrets`(OS 암호학적 난수)를 쓰는지.
    기본 난수는 시드를 알면 수열이 재현돼서, "언제 만들어졌는지"를 아는 사람이 후보를
    좁힐 여지가 남습니다. 닉네임은 익명성의 마지막 껍질이라 여기서 아끼지 않습니다.
    """
    source = (REPO_ROOT / "utils" / "duel_rules.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "generate_nickname")
    body = ast.get_source_segment(source, node)
    assert "secrets." in body
    assert "random." not in body, "generate_nickname() 이 재현 가능한 난수를 씁니다"


def test_ensure_nickname_returns_the_existing_one_without_writing():
    """이미 있으면 새로 만들지 않습니다 — 닉네임은 계좌에 고정입니다(5-5 재계산 금지)."""
    client = FakeClient(responses={
        (duel_db.NICKNAMES_TABLE, "select"): [{"account_id": "acc-1", "nickname": "잔잔한물결0001"}],
    })
    row = duel_db.ensure_nickname(client, "acc-1")
    assert row["nickname"] == "잔잔한물결0001"
    assert client.calls_for(duel_db.NICKNAMES_TABLE, "insert") == []


def test_ensure_nickname_creates_one_when_missing():
    client = FakeClient(responses={(duel_db.NICKNAMES_TABLE, "select"): []})
    row = duel_db.ensure_nickname(client, "acc-1")
    call = client.only_call(duel_db.NICKNAMES_TABLE, "insert")
    assert call.payload["account_id"] == "acc-1"
    assert call.payload["nickname"] == row["nickname"]
    # 🔴 계좌 id 가 닉네임 문자열에 섞이지 않았는지 (유도 금지 — 5-5).
    assert "acc-1" not in row["nickname"]


def test_ensure_nickname_retries_on_unique_conflict():
    """
    스키마 §6 이 요구하는 "난수 → unique 충돌 시 재시도". 첫 후보가 이미 쓰이는 이름이면
    새 후보로 다시 넣습니다. 앱이 "이미 있는지 먼저 조회"하지 않는 이유는 조회와 삽입 사이의
    경합을 앱이 막을 수 없기 때문입니다.
    """
    from test_duel_db import sequence
    client = FakeClient(responses={
        # 1차 select(내 것 없음) → 충돌 뒤 재확인 select(여전히 없음) → 성공
        (duel_db.NICKNAMES_TABLE, "select"): sequence([], [], []),
        (duel_db.NICKNAMES_TABLE, "insert"): sequence(
            Exception("duplicate key value violates unique constraint \"duel_nicknames_nickname_key\""),
            [{"account_id": "acc-1", "nickname": "두번째후보0002"}],
        ),
    })
    row = duel_db.ensure_nickname(client, "acc-1")
    assert row["nickname"] == "두번째후보0002"
    inserts = client.calls_for(duel_db.NICKNAMES_TABLE, "insert")
    assert len(inserts) == 2
    assert inserts[0].payload["nickname"] != inserts[1].payload["nickname"], \
        "재시도는 **새 후보**로 해야 합니다(같은 이름을 다시 넣으면 영원히 충돌)"


def test_ensure_nickname_yields_to_the_other_tab_on_a_race():
    """
    두 탭에서 동시에 눌렀을 때(= account_id 기본키 충돌) **먼저 만들어진 이름을 씁니다.**
    한 계좌에 이름이 둘이면 과거 발행 행과의 대응이 끊깁니다(철회 삭제가 새어 나갑니다).
    """
    from test_duel_db import sequence
    client = FakeClient(responses={
        (duel_db.NICKNAMES_TABLE, "select"): sequence(
            [], [{"account_id": "acc-1", "nickname": "먼저만들어진0007"}]),
        (duel_db.NICKNAMES_TABLE, "insert"):
            Exception("duplicate key value violates unique constraint \"duel_nicknames_pkey\""),
    })
    row = duel_db.ensure_nickname(client, "acc-1")
    assert row["nickname"] == "먼저만들어진0007"
    assert len(client.calls_for(duel_db.NICKNAMES_TABLE, "insert")) == 1


def test_ensure_nickname_does_not_swallow_real_errors():
    client = FakeClient(responses={
        (duel_db.NICKNAMES_TABLE, "select"): [],
        (duel_db.NICKNAMES_TABLE, "insert"): Exception("connection reset by peer"),
    })
    with pytest.raises(DuelDbError):
        duel_db.ensure_nickname(client, "acc-1")


# =============================================================================
# 4. 동의 철회 — work order 5-8
# =============================================================================
def _consent_row(**overrides):
    row = {"account_id": "acc-1", "consent_rank": True, "consent_return": True,
           "consent_holdings": True, "consent_quantity": True, "consent_buy_amount": True,
           "final_confirmed": True, "final_confirmed_at": "2026-08-01T10:00:00+09:00",
           "consent_real_principal_bracket": True, "revoked_at": None}
    row.update(overrides)
    return row


def test_revoke_consent_records_the_time_and_turns_everything_off():
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): [_consent_row()]})
    duel_db.revoke_consent(client, "acc-1", now_kst=datetime(2026, 8, 20, 21, 0, tzinfo=KST))

    payload = client.only_call(duel_db.CONSENT_TABLE, "update").payload
    assert payload["revoked_at"].startswith("2026-08-20")
    assert payload["final_confirmed"] is False
    assert payload["final_confirmed_at"] is None, \
        "최종확인을 끄면 시각도 함께 지워야 합니다(duel_consent_final_time CHECK)"
    for flag in duel_db.CONSENT_ITEM_FLAGS:
        assert payload[flag] is False
    assert payload[duel_db.CONSENT_REAL_PRINCIPAL_FLAG] is False, \
        "철회하면 실제 매입총합을 읽을 이유가 하나도 남지 않아야 합니다(§0-3-8)"


def test_revoke_consent_never_deletes_the_row():
    """
    🔴 5-8-3 — `revoked_at` 한 줄은 **남습니다.** 3개월 재동의 차단을 판정하려면 필요한
    비공개 관리 기록이고, 삭제 대상인 "발행된 공개 기록"과는 다른 것입니다.
    """
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): [_consent_row()]})
    duel_db.revoke_consent(client, "acc-1")
    assert client.calls_for(duel_db.CONSENT_TABLE, "delete") == [], "동의 행을 지우면 안 됩니다"

    source = (REPO_ROOT / "utils" / "duel_db.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "revoke_consent")
    assert ".delete(" not in ast.get_source_segment(source, node)


def test_revoking_twice_does_not_extend_the_block():
    """
    두 번 눌러도 `revoked_at` 을 다시 찍지 않습니다 — 찍으면 3개월 차단이 그만큼 연장되고,
    그건 버튼을 두 번 눌렀다는 이유로 사용자에게 불이익을 주는 일입니다.
    """
    already = _consent_row(final_confirmed=False, final_confirmed_at=None,
                           revoked_at="2026-08-01T10:00:00+09:00")
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): [already]})
    row = duel_db.revoke_consent(client, "acc-1")
    assert row["revoked_at"] == "2026-08-01T10:00:00+09:00"
    assert client.calls_for(duel_db.CONSENT_TABLE, "update") == []


def test_revoke_consent_without_a_prior_consent_is_a_clear_error():
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): []})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.revoke_consent(client, "acc-1")
    assert "철회할 공개 동의 기록이 없습니다" in str(excinfo.value)


@pytest.mark.parametrize("now,blocked", [
    (datetime(2026, 8, 20, 10, 0, tzinfo=KST), True),      # 철회 당일
    (datetime(2026, 11, 19, 23, 59, tzinfo=KST), True),    # 3개월 하루 전
    (datetime(2026, 11, 20, 9, 59, tzinfo=KST), True),     # 풀리기 1분 전
    (datetime(2026, 11, 20, 10, 0, tzinfo=KST), False),    # 정확히 3개월 — 이 순간부터 풀림
    (datetime(2027, 1, 1, 0, 0, tzinfo=KST), False),
])
def test_three_month_reconsent_block_boundaries(now, blocked):
    """5-8-2 — 정확히 3개월이 **되는 순간부터** 풀립니다(하루 더 미루지 않습니다)."""
    result = duel_rules.resolve_reconsent_block("2026-08-20T10:00:00+09:00", now)
    assert result["blocked"] is blocked
    assert result["unblocks_on"] == date(2026, 11, 20)


def test_no_revocation_means_no_block():
    assert duel_rules.resolve_reconsent_block(None)["blocked"] is False
    assert duel_rules.resolve_reconsent_block("")["blocked"] is False


def test_save_consent_is_blocked_for_three_months_after_revoking():
    """
    🔴 5-8-2 — 화면만 막으면 안 됩니다. **저장 경로**가 막아야 합니다.
    그리고 사용자에게 **언제 풀리는지 날짜**를 알려 줍니다(§0-1 / §0-3-4).
    """
    revoked = _consent_row(final_confirmed=False, final_confirmed_at=None,
                           revoked_at="2026-08-20T10:00:00+09:00")
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): [revoked]})
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.save_consent(client, "acc-1", consent_rank=True)

    message = str(excinfo.value)
    assert "3개월" in message
    assert "2026-11-20" in message, "언제 풀리는지 날짜를 알려 줘야 합니다"
    assert client.calls_for(duel_db.CONSENT_TABLE, "upsert") == [], "차단 중에는 저장하지 않습니다"


def test_save_consent_works_again_after_three_months():
    revoked = _consent_row(final_confirmed=False, final_confirmed_at=None,
                           revoked_at="2026-01-01T10:00:00+09:00")
    client = FakeClient(responses={(duel_db.CONSENT_TABLE, "select"): [revoked]})
    duel_db.save_consent(client, "acc-1", consent_rank=True)
    assert len(client.calls_for(duel_db.CONSENT_TABLE, "upsert")) == 1


def test_revoked_accounts_published_rows_are_deleted_at_every_date():
    """
    🔴 5-8-1 — *"그 계좌의 발행된 공개 기록을 **전부 영구 삭제**"*. 오늘 것만이 아니라
    **과거 순위·과거 수익률·과거 보유종목 행까지** 전부입니다.
    그래서 삭제 질의에 `published_date` 필터가 **있으면 안 됩니다.**
    """
    client = FakeClient()
    duel_db.delete_published_rows_for_nicknames(client, ["잔잔한물결0001", "포근한연잎0002"])

    deletes = client.calls_for(op="delete")
    assert {call.table for call in deletes} == {duel_db.PUBLIC_LEADERBOARD_TABLE,
                                                duel_db.PUBLIC_HOLDINGS_TABLE}
    for call in deletes:
        columns = {column for _op, column, _value in call.filters}
        assert columns == {"nickname"}, \
            f"철회 삭제에 날짜 필터가 붙어 있습니다({call.filters}) — 과거 기록이 남습니다"
        assert call.filter_map["nickname"] == ["잔잔한물결0001", "포근한연잎0002"]


def test_revocation_delete_is_set_based_not_one_query_per_nickname():
    """§0-3-2 — 닉네임이 200개여도 표당 질의 1개(청크 단위)."""
    names = [f"닉네임{index:04d}" for index in range(200)]
    client = FakeClient()
    duel_db.delete_published_rows_for_nicknames(client, names)
    assert len(client.calls_for(op="delete")) == 2, "표 2개 × 청크 1개 = 질의 2개여야 합니다"


def test_publish_batch_purges_revoked_accounts_before_anything_else():
    """
    발행 배치가 **가장 먼저** 철회 청소를 하는지. 순서를 뒤집으면, 오늘 발행이 중간에
    실패했을 때 철회한 사람의 과거 기록이 하루 더 남습니다.
    """
    client = _publish_client(account_count=0, revoked=[{"account_id": "acc-9",
                                                        "revoked_at": "2026-08-01T00:00:00+09:00"}],
                             nicknames=[{"account_id": "acc-9", "nickname": "떠난사람0009"}])
    duel_publish.run_publish_batch(client, TODAY)

    ops = [(call.table, call.op) for call in client.calls]
    first_delete = next(index for index, item in enumerate(ops) if item[1] == "delete")
    first_write = next((index for index, item in enumerate(ops) if item[1] == "insert"), len(ops))
    assert first_delete < first_write
    delete_names = [call.filter_map.get("nickname") for call in client.calls_for(op="delete")]
    assert ["떠난사람0009"] in delete_names


# =============================================================================
# 5. 최소 인원 500명 — work order 5-6
# =============================================================================
def test_minimum_participant_threshold_is_five_hundred():
    """오너 확정값(5-6). 이 숫자가 조용히 낮아지면 소수 N 역추적으로 익명성이 무너집니다."""
    assert duel_rules.MIN_PARTICIPANTS_FOR_PUBLICATION == 500


@pytest.mark.parametrize("count,publishable", [(0, False), (1, False), (499, False),
                                               (500, True), (501, True)])
def test_group_minimum_boundary(count, publishable):
    assert duel_rules.group_meets_minimum(count) is publishable


def _group(count, prefix="nick"):
    return [{"nickname": f"{prefix}{index:04d}", "twr_pct": float(index), "rank": index + 1,
             "positions": []} for index in range(count)]


def test_split_groups_by_threshold_at_499_and_500():
    groups = {("M1", "krw_1m_3m"): _group(499, "a"),
              ("M3", "krw_1m_3m"): _group(500, "b")}
    publishable, blocked = duel_publish.split_groups_by_threshold(groups)
    assert list(publishable) == [("M3", "krw_1m_3m")]
    assert list(blocked) == [("M1", "krw_1m_3m")]


def test_group_that_fell_below_the_threshold_has_its_old_rows_deleted():
    """
    🔴 5-6 — *"임계값 미만인 구간은 아예 발행하지 않습니다. **이미 발행돼 있던 행도
    제거합니다.**"* 어제 501명이었다가 오늘 499명이 된 경우가 정확히 이 경우입니다.
    """
    client = FakeClient(responses={
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): [
            {"published_date": "2026-08-18", "nickname": "어제사람0001"},
            {"published_date": "2026-08-18", "nickname": "어제사람0002"},
            {"published_date": "2026-08-19", "nickname": "어제사람0001"},
        ],
    })
    duel_db.delete_published_group(client, "M1", "krw_1m_3m")

    board_delete = client.only_call(duel_db.PUBLIC_LEADERBOARD_TABLE, "delete")
    assert board_delete.filter_map == {"window_type": "M1", "bracket_key": "krw_1m_3m"}
    assert "published_date" not in board_delete.filter_map, "과거 날짜도 지워야 합니다"

    holding_deletes = client.calls_for(duel_db.PUBLIC_HOLDINGS_TABLE, "delete")
    # 보유종목 표에는 bracket_key 컬럼이 없어서(스키마 §8-2) **그날 그 그룹에 있던 닉네임**
    # 으로만 지웁니다. 날짜를 뭉뚱그리면 다른 시즌의 정상 행까지 지울 수 있습니다.
    assert {call.filter_map["published_date"] for call in holding_deletes} == \
        {"2026-08-18", "2026-08-19"}


def test_group_that_was_never_published_sends_no_delete():
    client = FakeClient(responses={(duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): []})
    assert duel_db.delete_published_group(client, "M1", "krw_1m_3m") == 0
    assert client.calls_for(op="delete") == []


def test_publish_batch_checks_every_possible_group_for_stale_rows():
    """
    참가자가 **전부 사라진** 그룹의 과거 행도 지워야 합니다. "오늘 참가자가 있는 그룹"만
    청소하면 그런 그룹이 영원히 공개된 채 남습니다 — 한 명도 없는데 어제 순위표가 그대로
    보이는 상태가 이 모듈에서 가장 나쁜 실패입니다.
    """
    assert len(duel_publish.all_possible_groups()) == 3 * 9, "창유형 3 × 체급 9 = 27개(상수)"

    client = _publish_client(account_count=0, leaderboard_probe=[{"id": 1}])
    duel_publish.run_publish_batch(client, TODAY)
    probes = client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
    group_probes = [call for call in probes if "window_type" in call.filter_map]
    assert len(group_probes) == 27


def test_publish_batch_skips_the_group_sweep_when_nothing_was_ever_published():
    """초기 운영 기간(발행표가 완전히 빔)에는 27번이 전부 헛걸음이라 질의 1개로 끝냅니다."""
    client = _publish_client(account_count=0, leaderboard_probe=[])
    duel_publish.run_publish_batch(client, TODAY)
    probes = [call for call in client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE, "select")
              if "window_type" in call.filter_map]
    assert probes == []


# =============================================================================
# 6. 순위 계산 — work order 5-4-3
# =============================================================================
def test_ranking_is_descending_by_return():
    ranked, unrankable = duel_rules.rank_participants([
        {"nickname": "a", "twr_pct": -3.0}, {"nickname": "b", "twr_pct": 12.5},
        {"nickname": "c", "twr_pct": 0.0}])
    assert [(row["nickname"], row["rank"]) for row in ranked] == [("b", 1), ("c", 2), ("a", 3)]
    assert unrankable == []


def test_ties_share_a_rank_and_the_next_rank_skips():
    """
    동점은 **같은 순위**, 다음 순위는 건너뜁니다(1, 2, 2, 4). 억지로 다른 순위를 주려면
    어딘가에서 순서를 지어내야 하고, 그건 사실이 아닌 정보를 발행하는 일입니다(§0-1).

    ⚠️ 동점은 드문 일이 아닙니다 — 현금만 들고 있는 계좌의 TWR 은 정확히 0.000000% 입니다.
       (이 때문에 2026-08-20 에 발행표의 유니크 제약을 rank → nickname 으로 고쳤습니다.)
    """
    ranked, _ = duel_rules.rank_participants([
        {"nickname": "a", "twr_pct": 5.0}, {"nickname": "b", "twr_pct": 0.0},
        {"nickname": "c", "twr_pct": 0.0}, {"nickname": "d", "twr_pct": -1.0}])
    assert [(row["nickname"], row["rank"]) for row in ranked] == \
        [("a", 1), ("b", 2), ("c", 2), ("d", 4)]


def test_ranking_is_stable_across_two_runs():
    """배치를 두 번 돌려도 행 순서가 흔들리지 않아야 합니다(동점 안에서도)."""
    entries = [{"nickname": name, "twr_pct": 0.0} for name in ("c", "a", "b")]
    first, _ = duel_rules.rank_participants(entries)
    second, _ = duel_rules.rank_participants(list(reversed(entries)))
    assert [row["nickname"] for row in first] == [row["nickname"] for row in second] == \
        ["a", "b", "c"]


def test_participants_without_a_computable_return_are_separated_not_zeroed():
    """
    🔴 §0-1 — 수익률을 계산할 수 없는 계좌(개설 첫날 등)는 **0% 가 아닙니다.**
    0% 로 세우면 실제로 존재하지 않는 성적으로 남들 위나 아래에 서게 됩니다.
    """
    ranked, unrankable = duel_rules.rank_participants([
        {"nickname": "a", "twr_pct": 1.0}, {"nickname": "b", "twr_pct": None}])
    assert [row["nickname"] for row in ranked] == ["a"]
    assert [row["nickname"] for row in unrankable] == ["b"]
    assert all(row["twr_pct"] != 0 for row in unrankable)


def test_duplicate_nickname_in_one_group_stops_the_batch():
    with pytest.raises(DuelRuleError):
        duel_rules.rank_participants([{"nickname": "a", "twr_pct": 1.0},
                                      {"nickname": "a", "twr_pct": 2.0}])


# =============================================================================
# 7. 동의 게이팅과 NULL 규율 — work order 5-2-2 · 5-4-2 · §0-1
# =============================================================================
def test_partially_consented_account_is_refused_not_published_with_zeros():
    """
    🔴 "전부 아니면 전무"(5-2-2). 항목이 하나라도 빠진 계좌는 **빠진 필드를 0/빈 값으로
    채워 발행하지 않고**, 발행 자체를 거절합니다.

    (DB CHECK `duel_consent_final_requires_all` 이 이미 이 조합을 막지만, 이 확인이 지키는
     것은 DB 의 상태가 아니라 **우리 조회 필터**입니다 — 위층에서 `.eq("final_confirmed",
     True)` 를 실수로 빼면 PostgREST 는 조용히 전체 행을 돌려줍니다.)
    """
    for missing in duel_db.CONSENT_ITEM_FLAGS:
        with pytest.raises(DuelPublishError) as excinfo:
            duel_publish.assert_full_consent(_consent_row(**{missing: False}))
        assert missing in str(excinfo.value)


def test_unconfirmed_or_revoked_rows_are_refused():
    with pytest.raises(DuelPublishError):
        duel_publish.assert_full_consent(_consent_row(final_confirmed=False))
    with pytest.raises(DuelPublishError):
        duel_publish.assert_full_consent(_consent_row(revoked_at="2026-08-01T00:00:00+09:00"))


def test_fully_consented_row_passes():
    assert duel_publish.assert_full_consent(_consent_row()) is None


def test_withheld_return_is_none_never_zero_in_the_payload():
    """
    🔴 §0-1 — "수익률 0%"와 "수익률 없음"은 다른 말입니다. payload 에서 `None` 이
    `0`·`0.0`·`""` 로 바뀌지 않는지 못 박습니다(`or 0` 한 글자면 생기는 사고).
    """
    payload = duel_publish.leaderboard_payload(
        ("M1", "krw_1m_3m"),
        [{"nickname": "a", "twr_pct": None, "rank": 1},
         {"nickname": "b", "twr_pct": 0.0, "rank": 2}])
    assert payload[0]["twr_pct"] is None
    assert payload[0]["twr_pct"] != 0
    assert payload[0]["twr_pct"] != ""
    # 그리고 진짜 0% 인 사람의 값은 사라지면 안 됩니다(둘을 섞지 않기).
    assert payload[1]["twr_pct"] == 0.0
    assert payload[1]["twr_pct"] is not None


def test_leaderboard_payload_never_carries_identifiers():
    """
    🔴 스키마 §8 — 발행표에는 `user_id` 도 `account_id` 도 들어가지 않습니다. 조립 단계에서
    들고 다니던 작업용 필드가 payload 로 새지 않는지(whitelist 방식인지) 검사합니다.
    """
    payload = duel_publish.leaderboard_payload(
        ("M1", "krw_1m_3m"),
        [{"nickname": "a", "twr_pct": 1.0, "rank": 1,
          "account_id": "acc-1", "positions": [], "user_id": "user-1"}])
    assert set(payload[0]) == {"window_type", "bracket_key", "rank", "nickname", "twr_pct"}


def test_write_functions_refuse_identifier_fields_as_a_last_line_of_defence():
    client = FakeClient()
    with pytest.raises(DuelDbError) as excinfo:
        duel_db.write_public_leaderboard(client, TODAY, [
            {"window_type": "M1", "bracket_key": "krw_1m_3m", "rank": 1,
             "nickname": "a", "twr_pct": 1.0, "account_id": "acc-1"}])
    assert "account_id" in str(excinfo.value)
    assert client.calls_for(op="insert") == []


def test_holdings_payload_fills_all_four_fields_together():
    """
    5-2-2 의 "전부 아니면 전무" 때문에, 발행되는 보유종목 행은 **항상** 4개 필드가 채워집니다.
    "수량은 공개, 매입금액은 비공개" 같은 반쪽 행은 만들 수 있는 조합 자체가 없습니다.
    """
    payload = duel_publish.holdings_payload(("M1", "krw_1m_3m"), [{
        "nickname": "a", "twr_pct": 1.0, "rank": 1,
        "positions": [{"ticker": "005930", "stock_name": "삼성전자",
                       "quantity": 7, "avg_cost": 70000}]}])
    assert payload == [{"window_type": "M1", "nickname": "a", "ticker": "005930",
                        "stock_name": "삼성전자", "quantity": 7.0, "buy_amount": 490000.0}]


def test_account_with_no_positions_produces_no_holding_rows_not_zero_rows():
    """
    현금만 들고 있는 계좌는 **행을 하나도 만들지 않습니다.** 수량 0 짜리 행을 만들면
    "0주 보유"라는 사실이 아닌 정보가 됩니다(§0-1). 화면은 "보유 없음"으로 그리면 됩니다.
    """
    assert duel_publish.holdings_payload(
        ("M1", "krw_1m_3m"), [{"nickname": "a", "twr_pct": 1.0, "rank": 1, "positions": []}]) == []


def test_broken_position_numbers_stop_the_batch_instead_of_becoming_zero():
    with pytest.raises(DuelPublishError):
        duel_publish.holdings_payload(("M1", "krw_1m_3m"), [{
            "nickname": "a", "twr_pct": 1.0, "rank": 1,
            "positions": [{"ticker": "005930", "quantity": None, "avg_cost": 100}]}])


# =============================================================================
# 8. 실제 매입원가합계 — work order 5-3 (§0-3-8 이 가장 예민한 자리)
# =============================================================================
def _kr_holding(user_id, quantity, price, ticker="005930"):
    return {"user_id": user_id, "market": "KR", "ticker": ticker, "stock_name": "삼성전자",
            "quantity": quantity, "avg_purchase_price": price, "currency": "KRW"}


def test_real_principal_uses_the_scorecard_cost_rule():
    """
    매입원가 = 수량 × 평균매입가. 이 규칙은 "내 성적표"가 이미 갖고 있으므로
    (`scorecard_db.evaluate_holding()`), 여기서 다시 곱하지 않고 그 함수를 씁니다(§0-3-10).
    """
    summary = duel_publish.summarize_real_principal(
        [_kr_holding("u1", 10, 700_000), _kr_holding("u1", 3, 100_000, ticker="000660")])
    assert summary["status"] == duel_publish.PRINCIPAL_OK
    assert summary["krw_cost_basis"] == pytest.approx(7_300_000)
    assert duel_rules.assign_bracket(summary["krw_cost_basis"]) == "krw_5m_10m"


def test_no_holdings_is_not_zero_won():
    """
    🔴 §0-1 — "아직 아무것도 등록하지 않음"을 "0원어치 보유"로 바꾸면, 그 사람은 자기 것이
    아닌 최하위 체급(100만원 미만)에 들어갑니다. 그래서 값을 만들지 않고 구간 미적용입니다.
    """
    summary = duel_publish.summarize_real_principal([])
    assert summary["status"] == duel_publish.PRINCIPAL_NO_HOLDINGS
    assert summary["krw_cost_basis"] is None

    resolved = duel_publish.resolve_bracket_for_account(summary, None, TODAY)
    assert resolved["bracket_key"] == duel_rules.BRACKET_NONE_KEY


def test_mixed_currency_holdings_are_not_summed_into_one_krw_number():
    """
    🔴 §0-1 — 이 앱에는 **환율 시계열이 없습니다**
    (`scorecard_db.NO_FX_CONVERSION_NOTICE` 가 "두 통화의 금액을 하나로 합산한 총자산 숫자는
    어디에도 표시하지 않는다"고 못 박고 있습니다). 원화분만으로 체급을 매기면 실제보다
    가벼운 체급이 되어 **그 사용자에게 유리한 방향으로 사실과 다른 결과**가 됩니다.
    """
    summary = duel_publish.summarize_real_principal([
        _kr_holding("u1", 10, 700_000),
        {"user_id": "u1", "market": "US", "ticker": "AAPL", "stock_name": "Apple",
         "quantity": 5, "avg_purchase_price": 200, "currency": "USD"},
    ])
    assert summary["status"] == duel_publish.PRINCIPAL_FX_MIXED
    assert summary["krw_cost_basis"] is None
    assert summary["currencies"] == ["KRW", "USD"]
    assert duel_publish.resolve_bracket_for_account(summary, None, TODAY)["bracket_key"] \
        == duel_rules.BRACKET_NONE_KEY


def test_accounts_without_the_independent_consent_still_join_without_a_bracket():
    """
    5-2-4 — 실제 매입총합 사용에 동의하지 않은 사용자도 **순위표에는 참여합니다.**
    빠지는 것은 체급뿐입니다. (요약이 `None` = 그 사용자의 holdings 를 **읽지도 않았음**.)
    """
    resolved = duel_publish.resolve_bracket_for_account(None, None, TODAY)
    assert resolved["bracket_key"] == duel_rules.BRACKET_NONE_KEY
    assert resolved["fresh_source"] == "no_consent"


def test_only_consenting_users_ids_are_collected_for_the_holdings_read():
    """
    🔴 5-3 — *"동의 없는 사용자의 `holdings` 를 읽는 코드 경로가 **하나라도** 있으면
    §0-3-8 위반"*. 그 경로를 한 함수로 좁혀 두었으므로, 그 함수를 직접 검사합니다.
    """
    accounts = {"acc-1": {"id": "acc-1", "user_id": "user-1"},
                "acc-2": {"id": "acc-2", "user_id": "user-2"}}
    consents = [_consent_row(account_id="acc-1", consent_real_principal_bracket=True),
                _consent_row(account_id="acc-2", consent_real_principal_bracket=False)]
    assert duel_publish.consented_user_ids_for_real_principal(consents, accounts) == ["user-1"]


def test_holdings_are_never_read_when_nobody_consented():
    """동의자가 0명이면 실제 자산 표에 **질의 자체를 보내지 않습니다.**"""
    client = FakeClient()
    assert duel_db.fetch_real_principal_holdings(client, []) == []
    assert client.calls == [], "동의자가 없는데 holdings 를 조회했습니다"


def test_real_principal_fetch_requires_an_explicit_user_list():
    """
    "안 주면 전부"라는 편의 기본값이 **없어야** 합니다. 그 한 줄이 곧 5-3 위반입니다.
    (`report_db.fetch_all_holdings()` 는 전원을 읽는 함수라 여기서 쓰면 안 됩니다.)
    """
    parameters = inspect.signature(duel_db.fetch_real_principal_holdings).parameters
    assert list(parameters) == ["service_client", "user_ids"]
    assert parameters["user_ids"].default is inspect.Parameter.empty


def test_publish_module_does_not_use_report_dbs_fetch_all_holdings():
    """
    🔴 `report_db.fetch_all_holdings()` 는 **전체 사용자**의 보유종목을 읽습니다(리포트
    배치는 전원이 대상이라 그게 맞습니다). 여기서 그걸 부르면 동의하지 않은 사람의 자산이
    이 배치의 메모리에 올라오고, 그 순간 5-3 위반입니다.
    """
    for name in ("duel_publish.py", "duel_db.py"):
        code = _executable_source(name)
        assert "fetch_all_holdings" not in code, f"{name} 이 전체 보유종목 조회를 부릅니다"
        assert "report_db" not in code


# =============================================================================
# 9. 하루치 발행 배치 — 전량 재작성(5-4-4) · 순서 · §0-3-2
# =============================================================================
def _in_filtered(rows, column):
    """
    `in` 필터를 실제로 적용하는 가짜 응답. 진짜 PostgREST 와 같게 동작해야, 청크로 나눠
    조회하는 코드가 "매 청크마다 전체를 받는" 비현실적인 상황에서 통과해 버리는 일이
    없습니다(그 상황에서만 안 보이는 버그가 실제로 있습니다 — 합계 중복 계산).
    """
    def resolve(query):
        wanted = None
        for op, name, value in query.filters:
            if op == "in" and name == column:
                wanted = set(value)
        if wanted is None:
            return list(rows)
        return [row for row in rows if str(row.get(column)) in wanted]
    return resolve


def _publish_client(account_count, *, consented_principal=True, revoked=None,
                    nicknames=None, leaderboard_probe=None, positions=None,
                    twr_pct_offset=0.0, existing_assignments=None):
    """
    발행 배치용 가짜 클라이언트. `duel_public_consent` 표를 두 가지 목적(발행 대상 / 철회
    목록)으로 조회하므로, 필터를 보고 갈라 주는 callable 로 응답을 지정합니다.
    """
    accounts = [{"id": f"acc-{i}", "user_id": f"user-{i}", "window_type": "M1",
                 "status": "active", "seed_amount": 10_000_000, "currency": "KRW",
                 "anchor_date": "2026-01-02"} for i in range(account_count)]
    consents = [_consent_row(account_id=f"acc-{i}",
                             consent_real_principal_bracket=consented_principal)
                for i in range(account_count)]
    revoked_rows = list(revoked or [])

    def consent_select(query):
        if ("not.is", "revoked_at", "null") in query.filters:
            return revoked_rows
        return consents

    snapshots = []
    for index in range(account_count):
        snapshots.append({"account_id": f"acc-{index}", "snapshot_date": "2026-08-18",
                          "total_value": 10_000_000, "cash_flow_amount": 10_000_000})
        snapshots.append({"account_id": f"acc-{index}", "snapshot_date": "2026-08-19",
                          "total_value": 10_000_000 * (1 + (index % 5) / 100.0)
                          + twr_pct_offset, "cash_flow_amount": 0})

    def leaderboard_select(query):
        if "window_type" in query.filter_map:
            return []                     # 미달 그룹 청소 점검 — 과거 발행 없음
        return list(leaderboard_probe if leaderboard_probe is not None else [])

    return FakeClient(responses={
        (duel_db.CONSENT_TABLE, "select"): consent_select,
        (duel_db.ACCOUNTS_TABLE, "select"): accounts,
        # ⚠️ 청크마다 **전체 목록**을 돌려주면 안 됩니다(실제 PostgREST 는 in 필터를
        #    적용하므로). 그러면 계좌가 200개를 넘는 순간 같은 사람의 보유종목이 여러 번
        #    세어져 매입원가합계가 부풀고, 체급이 조용히 달라집니다.
        ("holdings", "select"): _in_filtered(
            [_kr_holding(f"user-{i}", 10, 700_000) for i in range(account_count)], "user_id"),
        (duel_db.BRACKET_ASSIGNMENTS_TABLE, "select"): list(existing_assignments or []),
        (duel_db.DAILY_SNAPSHOTS_TABLE, "select"): snapshots,
        (duel_db.POSITIONS_TABLE, "select"): list(positions if positions is not None else [
            {"account_id": f"acc-{i}", "ticker": "005930", "stock_name": "삼성전자",
             "quantity": 5, "avg_cost": 70000, "status": "active"}
            for i in range(account_count)]),
        (duel_db.NICKNAMES_TABLE, "select"): _in_filtered(
            list(nicknames if nicknames is not None else [
                {"account_id": f"acc-{i}", "nickname": f"닉네임{i:04d}"}
                for i in range(account_count)]), "account_id"),
        (duel_db.PUBLIC_LEADERBOARD_TABLE, "select"): leaderboard_select,
    })


def test_publish_batch_full_rewrite_deletes_todays_rows_before_inserting():
    """
    🔴 5-4-4 — *"그날 발행분을 통째로 갈아끼우는 방식"*. 부분 갱신은 "어제는 있었는데 오늘은
    자격을 잃은 행"을 남깁니다. 통째로 지우고 다시 쓰면 남는 경우가 구조적으로 없습니다.
    """
    client = _publish_client(account_count=500)
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["leaderboard_rows"] == 500

    ops = [(call.table, call.op) for call in client.calls]
    date_deletes = [index for index, call in enumerate(client.calls)
                    if call.op == "delete" and call.filter_map.get("published_date") == "2026-08-20"]
    inserts = [index for index, item in enumerate(ops)
               if item[1] == "insert" and item[0] in (duel_db.PUBLIC_LEADERBOARD_TABLE,
                                                      duel_db.PUBLIC_HOLDINGS_TABLE)]
    assert len(date_deletes) == 2, "두 발행표 각각 그날 행을 통째로 지워야 합니다"
    assert max(date_deletes) < min(inserts), "삭제가 삽입보다 먼저여야 합니다"


def test_running_twice_on_the_same_day_does_not_duplicate_rows():
    """
    같은 날 두 번 돌려도 그날 행이 중복되지 않습니다 — 두 번째 실행도 **먼저 그날 것을 전부
    지우고** 다시 넣기 때문입니다. (그리고 DB 의 유니크 제약
    `duel_public_leaderboard_participant_unique` 가 마지막 방어선으로 남습니다.)
    """
    for _run in range(2):
        client = _publish_client(account_count=500)
        summary = duel_publish.run_publish_batch(client, TODAY)
        assert summary["leaderboard_rows"] == 500
        rows = [row for call in client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE, "insert")
                for row in call.rows]
        keys = [(row["published_date"], row["window_type"], row["bracket_key"], row["nickname"])
                for row in rows]
        assert len(keys) == len(set(keys)), "같은 참가자가 한 날짜에 두 번 실렸습니다"


def test_publish_batch_publishes_nothing_below_the_threshold():
    client = _publish_client(account_count=499)
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["leaderboard_rows"] == 0
    assert summary["holdings_rows"] == 0
    assert summary["blocked_groups"] == ["M1/krw_5m_10m"]
    assert client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE, "insert") == []


def test_publish_batch_publishes_at_exactly_the_threshold():
    client = _publish_client(account_count=500)
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["published_groups"] == ["M1/krw_5m_10m"]
    assert summary["leaderboard_rows"] == 500
    assert summary["holdings_rows"] == 500


def test_publish_batch_skips_accounts_without_a_nickname_and_says_so():
    """
    닉네임이 없는 계좌는 발행하지 않고, **그 사실을 요약에 남깁니다**(§0-1 — 조용히 빠지는
    계좌를 만들지 않기). 배치가 닉네임을 대신 만들어 주지도 않습니다.
    """
    nicknames = [{"account_id": f"acc-{i}", "nickname": f"닉네임{i:04d}"} for i in range(499)]
    client = _publish_client(account_count=500, nicknames=nicknames)
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["leaderboard_rows"] == 0, "499명이 되어 최소 인원 미달"
    assert [row["reason"] for row in summary["skipped"]] == [duel_publish.SKIP_NO_NICKNAME]
    assert client.calls_for(duel_db.NICKNAMES_TABLE, "insert") == []


def test_publish_batch_skips_accounts_whose_return_cannot_be_computed():
    """개설 첫날처럼 구간 수익률이 없는 계좌는 0% 로 세우지 않고 뺍니다(§0-1)."""
    client = _publish_client(account_count=3)
    # 스냅샷을 계좌당 1개(개설일)만 주면 TWR 은 'INSUFFICIENT' 입니다.
    client.responses[(duel_db.DAILY_SNAPSHOTS_TABLE, "select")] = [
        {"account_id": f"acc-{i}", "snapshot_date": "2026-08-19",
         "total_value": 10_000_000, "cash_flow_amount": 10_000_000} for i in range(3)]
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["group_counts"] == {}
    assert {row["reason"] for row in summary["skipped"]} == {duel_publish.SKIP_NO_TWR}


def test_dry_run_writes_absolutely_nothing():
    """오너가 "무엇이 발행될 뻔했는지"를 먼저 눈으로 볼 수 있어야 합니다(§0-3-6 의 정신)."""
    client = _publish_client(account_count=500)
    summary = duel_publish.run_publish_batch(client, TODAY, dry_run=True)
    assert summary["leaderboard_rows"] == 500
    assert client.calls_for(op="insert") == []
    assert client.calls_for(op="delete") == []
    assert client.calls_for(op="update") == []
    assert client.calls_for(op="upsert") == []


def test_publish_batch_keeps_the_season_bracket_and_does_not_rewrite_it():
    """
    시즌 중이면 기존 배정이 이기고, **배정 기록을 다시 쓰지도 않습니다**(§0-3-2 이자 5-3).
    """
    existing = [{"account_id": f"acc-{i}", "season_key": SEASON, "bracket_key": "krw_100m_plus"}
                for i in range(500)]
    client = _publish_client(account_count=500, existing_assignments=existing)
    summary = duel_publish.run_publish_batch(client, TODAY)

    assert summary["published_groups"] == ["M1/krw_100m_plus"], \
        "오늘 계산하면 500만~1천만이지만 시즌 중이라 기존 체급이 이겨야 합니다"
    assert client.calls_for(duel_db.BRACKET_ASSIGNMENTS_TABLE, "insert") == []
    assert summary["principal_status_counts"] == {"kept": 500}


def test_publish_batch_reads_the_season_assignments_before_deciding():
    """
    배치가 체급 배정 기록을 **읽지 않고** 넘어가면 시즌 고정이 조용히 사라집니다.
    그 질의가 실제로 나가는지 고정합니다.
    """
    client = _publish_client(account_count=3)
    duel_publish.run_publish_batch(client, TODAY)
    call = client.only_call(duel_db.BRACKET_ASSIGNMENTS_TABLE, "select")
    assert call.filter_map == {"season_key": SEASON}


@pytest.mark.parametrize("account_count", [3, 50, 900])
def test_publish_batch_query_count_does_not_scale_with_accounts(account_count):
    """
    🔴 §0-3-2 회귀 테스트(작업지시서 2-7 이 명시적으로 요구한 것).
    `apply_monthly_deposits` 의 같은 성격 테스트를 그대로 본떴습니다.

    계좌가 3개든 900개든 **고정 왕복 수는 그대로**이고, 늘어나는 것은 "요청 하나가 지나치게
    커지지 않게 자르는" 청크 수뿐입니다 — 계좌마다 부르는 것이 아닙니다. 사용자가 10명일
    때는 계좌별 루프도 잘 돌아갑니다. 그래서 위험합니다.
    """
    client = _publish_client(account_count=account_count)
    duel_publish.run_publish_batch(client, TODAY)

    chunks = -(-account_count // duel_db.CHUNK_SIZE)
    published = duel_rules.group_meets_minimum(account_count)

    # 계좌 수와 무관하게 정확히 1번씩만 나가는 조회들.
    for table, op in ((duel_db.ACCOUNTS_TABLE, "select"),
                      (duel_db.BRACKET_ASSIGNMENTS_TABLE, "select"),
                      (duel_db.DAILY_SNAPSHOTS_TABLE, "select"),
                      (duel_db.POSITIONS_TABLE, "select")):
        assert len(client.calls_for(table, op)) == 1, f"{table}.{op} 가 1번이 아닙니다"
    assert len(client.calls_for(duel_db.CONSENT_TABLE, "select")) == 2   # 발행 대상 + 철회

    # 청크에 비례하는 것들(계좌 수가 아니라 **청크 수**).
    assert len(client.calls_for(duel_db.NICKNAMES_TABLE, "select")) == chunks
    assert len(client.calls_for("holdings", "select")) == chunks
    assert len(client.calls_for(duel_db.BRACKET_ASSIGNMENTS_TABLE, "insert")) == chunks

    inserts = (client.calls_for(duel_db.PUBLIC_LEADERBOARD_TABLE, "insert")
               + client.calls_for(duel_db.PUBLIC_HOLDINGS_TABLE, "insert"))
    assert len(inserts) == (2 * chunks if published else 0)

    # 그날 발행분 통째 삭제 2개 + (발행표가 비어 있으므로) 미달 그룹 청소 0개.
    assert len(client.calls_for(op="delete")) == 2

    # 총합이 "상수 + 청크 × 상수" 꼴인지 — 계좌 수에 비례하는 항이 없어야 합니다.
    fixed = 7                       # 계좌·배정·스냅샷·포지션·동의2·발행표 존재확인
    per_chunk = 3 + (2 if published else 0)
    assert len(client.calls) == fixed + chunks * per_chunk + 2


def test_publish_batch_with_no_participants_writes_nothing_but_still_cleans():
    client = _publish_client(account_count=0)
    summary = duel_publish.run_publish_batch(client, TODAY)
    assert summary["consent_count"] == 0
    assert summary["leaderboard_rows"] == 0
    assert client.calls_for(op="insert") == []
    # 그래도 그날 발행분 삭제는 돕니다 — 어제까지 있던 그룹이 오늘 0명이 됐을 수 있습니다.
    assert len(client.calls_for(op="delete")) == 2


def test_summary_lines_show_blocked_groups_and_skipped_accounts():
    """§0-1 — 빠진 것과 막힌 것이 로그에 드러나야 합니다(조용히 넘어가지 않기)."""
    client = _publish_client(account_count=499)
    lines = duel_publish.format_summary_lines(duel_publish.run_publish_batch(client, TODAY))
    text = "\n".join(lines)
    assert "499명" in text
    assert "미발행" in text and "500" in text


# =============================================================================
# 10. 🔴 §0-3-8 구조 검사 (AST) — "조심했는가"가 아니라 "할 수 있는가"
# =============================================================================
def _module_ast(name):
    source = (REPO_ROOT / "utils" / name).read_text(encoding="utf-8")
    return ast.parse(source), source


def _executable_source(name):
    """
    주석과 **문자열 리터럴(docstring 포함)** 을 걷어낸 소스. "실제로 실행되는 코드"만 봅니다.

    이 파일의 여러 검사가 "이 이름이 코드에 없어야 한다"를 봅니다. 그런데 이 저장소는
    docstring 에 근거를 길게 적는 관례라, 문자열까지 세면 **설명을 잘 쓸수록 검사가 실패**
    합니다. 그건 검사가 잘못된 것이지 코드가 잘못된 게 아닙니다.
    """
    import io
    import tokenize

    source = (REPO_ROOT / "utils" / name).read_text(encoding="utf-8")
    pieces = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        pieces.append(token.string)
    return "\n".join(pieces)


def _functions(tree):
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


NEW_USER_FUNCTIONS = ("revoke_consent", "ensure_nickname", "fetch_my_consent")


@pytest.mark.parametrize("name", NEW_USER_FUNCTIONS)
def test_new_user_facing_functions_never_reach_for_the_batch_key(name):
    """
    🔴 새 A 절 함수들이 배치 키를 건드리지 않는지(§0-3-8 격리 회귀 고정).
    `test_duel_db.py::test_opt_in_does_not_reach_for_the_batch_key()` 와 같은 검사이고,
    함수 본문만 AST 로 떼어 보므로 절 구분 주석이 바뀌어도 검사가 따라갑니다.
    """
    tree, source = _module_ast("duel_db.py")
    body = ast.get_source_segment(source, _functions(tree)[name])
    for forbidden in ("service_role", "SERVICE_ROLE_KEY_ENV", "create_service_client",
                      "_read_service_env", "os.environ", "getenv"):
        assert forbidden not in body, f"{name} 이 {forbidden} 을(를) 건드립니다"


@pytest.mark.parametrize("name", NEW_USER_FUNCTIONS)
def test_new_user_facing_functions_only_write_the_two_user_tables(name):
    """
    스키마 §9 가 사용자에게 insert/update 를 준 표는 `duel_orders` · `duel_public_consent` ·
    `duel_nicknames`(옵트인 시 1회) 셋뿐입니다. 그 밖의 표에 쓰면 안 됩니다.
    """
    from test_duel_db import _write_targets
    tree, _source = _module_ast("duel_db.py")
    targets = _write_targets(_functions(tree)[name])
    assert targets <= {"CONSENT_TABLE", "NICKNAMES_TABLE"}, \
        f"{name} 이 사용자 권한 밖의 표에 씁니다: {targets}"


def test_only_the_batch_section_writes_the_publish_tables():
    """
    🔴 발행표에 **쓰는** 함수가 전부 B 절에 있는지. 이 검사가 실패하는 순간은 누군가
    화면 코드에서 순위표를 직접 쓰려고 한 순간이고, 그러면 앱 서버에 배치 키가 필요해집니다.
    """
    tree, source = _module_ast("duel_db.py")
    from test_duel_db import _write_targets

    b_start = source.index("#  B 절 \u2014")
    writers = []
    for name, node in _functions(tree).items():
        targets = _write_targets(node)
        if {"PUBLIC_LEADERBOARD_TABLE", "PUBLIC_HOLDINGS_TABLE"} & targets:
            writers.append(name)
            assert source.index(f"def {name}(") > b_start, f"{name} 이 B 절 밖에 있습니다"
    assert set(writers) == {"delete_published_rows_for_date",
                            "delete_published_rows_for_nicknames",
                            "delete_published_group",
                            "write_public_leaderboard",
                            "write_public_holdings"}, \
        f"발행표에 쓰는 함수 목록이 바뀌었습니다: {sorted(writers)}"


def test_publish_module_never_creates_its_own_supabase_client():
    """
    발행 배치는 클라이언트를 **인자로만** 받습니다. 여기서 만들기 시작하면 이 파일이
    환경변수를 읽게 되고, 그 순간 "어디서 부르든 도는 코드"가 됩니다(§0-3-8).
    """
    code = _executable_source("duel_publish.py")
    for forbidden in ("create_service_client", "os.environ", "getenv", "create_client"):
        assert forbidden not in code, f"duel_publish.py 가 {forbidden} 을(를) 씁니다"


def test_publish_module_touches_supabase_only_through_duel_db():
    """
    `utils/duel_db.py` 가 "유일한 접착제"라는 계층 규약을 고정합니다. 발행 코드가 직접
    `.table(...)` 을 부르기 시작하면, 발행표를 건드리는 자리가 두 파일로 흩어집니다.
    """
    tree, _source = _module_ast("duel_publish.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("table", "rpc"), \
                "duel_publish.py 가 Supabase 를 직접 부릅니다(전부 duel_db 를 통해야 합니다)"


def test_publish_module_does_not_import_the_private_source_tables_by_name():
    """
    5-4-5 — 순위표 **읽기** 경로는 원본 표를 import 조차 하면 안 됩니다. 발행 배치는 원본을
    읽어야 하는 유일한 코드라 예외지만, 그 접근이 전부 `duel_db` 의 이름 붙은 함수를 통하는지
    (표 이름 문자열을 직접 쓰지 않는지) 확인합니다.
    """
    tree, _source = _module_ast("duel_publish.py")
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for table in ("holdings", "duel_positions", "profiles", "duel_cash_ledger",
                  "duel_public_leaderboard", "duel_public_holdings", "duel_nicknames",
                  "duel_public_consent"):
        assert table not in literals, f"duel_publish.py 에 표 이름 문자열({table!r})이 있습니다"


def test_every_new_public_function_has_a_docstring():
    """`tests/test_duel_db.py` 의 같은 규약 — 이 모듈의 모든 공개 함수에 설명이 있어야 합니다."""
    tree, _source = _module_ast("duel_publish.py")
    missing = [node.name for node in tree.body
               if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
               and not ast.get_docstring(node)]
    assert missing == [], f"docstring 이 없는 공개 함수: {missing}"


def test_rules_module_publish_section_has_no_io():
    """
    `utils/duel_rules.py` 는 표준 라이브러리 말고 아무것도 import 하지 않습니다.
    5단계에서 추가한 절도 그 규율을 지키는지(파일·소켓·Supabase 없음).
    """
    tree, _source = _module_ast("duel_rules.py")
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "math", "datetime", "decimal", "secrets"}, \
        f"duel_rules.py 가 표준 라이브러리 밖을 import 합니다: {sorted(imported)}"


def test_schema_file_declares_the_new_tables_and_constraint():
    """
    🔴 2026-08-20 에 스키마를 두 군데 고쳤습니다. 그 사실이 파일에 그대로 남아 있는지
    (누가 되돌리면 여기서 잡히도록) 확인합니다. 근거는 작업 보고 (g) 참고.
    """
    schema = (REPO_ROOT / "sql" / "duel_schema.sql").read_text(encoding="utf-8")

    # ① 체급 배정 기록 표 — 없으면 "시즌 중 체급 고정"을 저장할 자리가 없습니다.
    assert "create table if not exists public.duel_bracket_assignments" in schema
    assert "primary key (account_id, season_key)" in schema
    # 배치에도 update/delete 를 주지 않는 것이 그 규칙의 강제 장치입니다.
    assert "revoke update, delete on public.duel_bracket_assignments from service_role" in schema
    assert "grant  select, insert on public.duel_bracket_assignments to service_role" in schema

    # ② 순위표 유니크 제약 — 동점자 두 명이 들어갈 수 있어야 합니다(rank 가 아니라 nickname).
    assert "duel_public_leaderboard_participant_unique" in schema
    assert "unique (published_date, window_type, bracket_key, nickname)" in schema
    assert "drop constraint if exists duel_public_rank_unique" in schema, \
        "예전 제약을 떼는 마이그레이션 한 줄이 있어야 이미 설치한 프로젝트가 고쳐집니다"
    # 읽기 성능은 같은 컬럼의 일반 인덱스로 유지합니다.
    assert "duel_public_leaderboard_group_rank_idx" in schema


def test_publish_batch_requires_an_explicit_date():
    """
    🔴 §0-1 — 이 모듈은 "오늘"을 스스로 정하지 않습니다. 배치가 자정 근처에 돌거나 하루
    늦게 돌면 발행일이 조용히 틀어지고, 그건 나중에 복원할 수 없는 오염입니다.
    (`duel_batch.run_nightly_batch()` 가 `target_date` 를 필수로 받는 것과 같은 규약.)
    """
    parameters = inspect.signature(duel_publish.run_publish_batch).parameters
    assert parameters["published_date"].default is inspect.Parameter.empty

    client = _publish_client(account_count=0)
    with pytest.raises(DuelPublishError):
        duel_publish.run_publish_batch(client, None)
    with pytest.raises(DuelPublishError):
        duel_publish.run_publish_batch(client, "어제")


def test_publish_module_does_not_reach_into_other_modules_private_functions():
    """
    남의 모듈의 밑줄 함수(`duel_db._iso_date` 등)를 가로질러 부르지 않는지.
    가로질러 쓰기 시작하면, 그 함수를 고치는 사람이 영향 범위를 알 수 없게 됩니다.
    """
    tree, _source = _module_ast("duel_publish.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in ("duel_db", "duel_rules", "duel_batch", "scorecard_db"):
                assert not node.attr.startswith("_"), \
                    f"duel_publish.py 가 {node.value.id}.{node.attr} (비공개)를 부릅니다"
