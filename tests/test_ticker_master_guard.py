# tests/test_ticker_master_guard.py
"""
🛡️ 전체 상장종목 마스터(kr_ticker_master.json) 문지기 검사 (2026-09-08 신설)

왜 생겼는가 — 그날 실제로 난 사고:
  2026-09-08 16:11 `Daily Market Scraper` 에서 FinanceDataReader 의 StockListing('KRX') 가
  "HTTP Error 404: Not Found" 로 실패했고, StockListing('ETF/KR') 만 1,167건 성공했습니다.
  예전 코드는 "0건이 아니면 저장" 이라 주식 2,873 + ETF 1,167 = 4,040건짜리 정상 파일을
  **ETF 1,167건만 든 파일로 덮어썼습니다.** 그날은 뒤 단계가 실패해 커밋이 안 돼 저장소
  파일이 우연히 살아남았을 뿐입니다. 신 경로(NAVER_SOURCE=new_api)는 종목 선별을 이 파일
  한 곳에 의존하므로, ETF 만 남은 마스터면 **후보 전부가 걸러져 0건**이 됩니다.

무엇을 못 박는가:
  ① 원천 하나(주식 또는 ETF)가 실패하면 **기존 파일이 한 바이트도 안 바뀐다** (사고 모양 그대로 재현).
  ② 그 사실이 로그 한 줄로 끝나지 않고 **기록(_ticker_master_refresh) → 상태(ticker_master_status)
     → 문장(data_sanity.ticker_master_notice) → Actions `::warning` → 스냅샷 metadata → 화면 배너**
     까지 이어진다(§0-1 "로그만 남기는 것은 조치가 아니다").
  ③ 둘 다 성공한 평소 날은 예전과 똑같이 파일을 쓴다.

⚠️ 모든 파일 쓰기는 `tmp_path` 안에서만 합니다. 실전 `data/` 는 읽지도 쓰지도 않습니다.
실행: python -m pytest tests/test_ticker_master_guard.py -v
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.append(str(REPO_ROOT))
sys.path.append(str(Path(__file__).parent))

# 무음 통과 방지 하네스는 `tests/conftest.py` 한 곳에만 있습니다.
from conftest import FAILURES, check  # noqa: E402,F401

import collector_kospi200 as K  # noqa: E402
from utils import data_sanity  # noqa: E402

MASTER = K.KR_TICKER_MASTER_FILENAME


# ─────────────────────────────────────────────────────────────────────────────
# 공용 가짜 FDR 응답 — 실제 FDR 0.9.x 의 컬럼 이름 그대로(KRX: Code/Name/Market, ETF: Symbol/Name)
# ─────────────────────────────────────────────────────────────────────────────
def _krx_df(n=5):
    rows = [{"Code": f"{i:06d}", "Name": f"주식{i}", "Market": "KOSPI" if i % 2 else "KOSDAQ"} for i in range(1, n + 1)]
    return pd.DataFrame(rows)


def _etf_df(n=1167):
    # 2026-09-08 실측: ETF/KR 은 1,167건, 컬럼은 Symbol/Name 이고 Market 컬럼이 없습니다.
    return pd.DataFrame([{"Symbol": f"{400000 + i:06d}", "Name": f"ETF{i}"} for i in range(n)])


def _krx_404():
    # pandas.read_csv(url) 이 raw.githubusercontent.com 에서 받는 그 예외 — str() 이 정확히
    # "HTTP Error 404: Not Found" 입니다(그날 로그 문구와 동일).
    raise HTTPError("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/x.csv",
                    404, "Not Found", hdrs=None, fp=None)


class _Fdr:
    """StockListing(market) 을 시나리오별로 흉내 냅니다."""

    def __init__(self, krx, etf):
        self._krx, self._etf = krx, etf

    def StockListing(self, market):
        fn = {"KRX": self._krx, "ETF/KR": self._etf}[market]
        return fn()


def _seed_existing_master(tmp_path, generated_at="2026-09-07 16:11"):
    """어제 자 정상 마스터(주식 + ETF)를 tmp 에 심고 (경로, sha256) 을 돌려줍니다."""
    payload = {
        "metadata": {"generated_at": generated_at,
                     "source": "FinanceDataReader StockListing('KRX') + StockListing('ETF/KR')",
                     "count": 4},
        "stocks": [
            {"code": "005930", "name": "삼성전자", "market": "KOSPI", "type": "STOCK"},
            {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "type": "STOCK"},
            {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "type": "STOCK"},
            {"code": "069500", "name": "KODEX 200", "market": None, "type": "ETF"},
        ],
    }
    path = tmp_path / MASTER
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def _fake_fdr_and_clean_record(monkeypatch):
    """FDR 가 설치돼 있다고 보고, 각 테스트 뒤 갱신 기록을 되돌립니다(테스트끼리 섞이지 않게)."""
    monkeypatch.setattr(K, "HAS_FDR", True)
    K._note_ticker_master_refresh(attempted=False, written=False, failed_sources=[], reason=None)
    yield
    K._note_ticker_master_refresh(attempted=False, written=False, failed_sources=[], reason=None)


# ─────────────────────────────────────────────────────────────────────────────
# ① 사고 재현 — KRX 404 + ETF 1,167건 성공 → 기존 파일 그대로
# ─────────────────────────────────────────────────────────────────────────────
def test_incident_2026_09_08_krx_404_keeps_existing_file(monkeypatch, tmp_path, capsys):
    path, before = _seed_existing_master(tmp_path)
    monkeypatch.setattr(K, "fdr", _Fdr(krx=_krx_404, etf=_etf_df))

    result = K.run_kr_ticker_master_collector(data_dir=str(tmp_path))
    out = capsys.readouterr().out

    check(result is None, "반쪽짜리면 경로를 돌려주지 않음(None)")
    check(hashlib.sha256(path.read_bytes()).hexdigest() == before, "🔴 기존 파일이 한 바이트도 안 바뀜")
    payload = json.loads(path.read_text(encoding="utf-8"))
    check(sum(1 for s in payload["stocks"] if s["type"] == "STOCK") == 3, "기존 파일의 주식 3건이 그대로 남아 있음")
    check(payload["metadata"]["generated_at"] == "2026-09-07 16:11", "기존 파일의 날짜도 그대로(오늘 날짜로 위장 안 함)")
    check(not (tmp_path / f".{MASTER}.tmp").exists(), "임시 파일 잔재 없음")
    check("ETF/KR" in out and "1167건 반영" in out, "ETF 는 실제로 1,167건 성공했음이 로그에 남음(사고 모양 그대로)", f"({out[:300]!r})")
    check("파일을 쓰지 않습니다" in out and "STOCK" in out, "🚨 로그에 '파일을 쓰지 않는다'와 실패 원천이 찍힘")
    check("404" in out, "실패 사유(404)가 로그에 그대로")
    # 실전 data/ 는 건드리지 않았는지 — 이 테스트가 만든 파일은 전부 tmp 아래
    check(str(path).startswith(str(tmp_path)), "🔴 tmp 안에서만 파일을 다룸")


def test_etf_failure_also_keeps_existing_file(monkeypatch, tmp_path):
    """반대 방향(주식 성공 + ETF 실패)도 반쪽입니다 — '내 성적표' 이름 검색에서 ETF 전부가 사라집니다."""
    path, before = _seed_existing_master(tmp_path)

    def _etf_boom():
        raise RuntimeError("etfItemList 응답 형식 변경 시뮬레이션")

    monkeypatch.setattr(K, "fdr", _Fdr(krx=_krx_df, etf=_etf_boom))
    result = K.run_kr_ticker_master_collector(data_dir=str(tmp_path))
    check(result is None, "ETF 원천 실패도 저장 거부")
    check(hashlib.sha256(path.read_bytes()).hexdigest() == before, "기존 파일 그대로")
    rec = K.ticker_master_status(path=str(path))
    check(rec["refresh_failed_sources"] == ["ETF"], "실패 원천이 ETF 로 기록됨", f"({rec})")


def test_zero_rows_from_a_source_counts_as_failure(monkeypatch, tmp_path):
    """예외 없이 '컬럼이 다른 빈 표'가 와도 0건이면 실패입니다(예전 코드는 이 경우도 ETF 만 저장)."""
    path, before = _seed_existing_master(tmp_path)
    monkeypatch.setattr(K, "fdr", _Fdr(krx=lambda: pd.DataFrame([{"엉뚱한컬럼": "x"}]), etf=_etf_df))
    result = K.run_kr_ticker_master_collector(data_dir=str(tmp_path))
    check(result is None, "주식 0건이면 저장 거부")
    check(hashlib.sha256(path.read_bytes()).hexdigest() == before, "기존 파일 그대로")
    rec = K.ticker_master_status(path=str(path))
    check(rec["refresh_failed_sources"] == ["STOCK"] and "0건" in (rec["refresh_reason"] or ""),
          "0건 사유가 기록에 남음", f"({rec})")


def test_failure_with_no_existing_file_creates_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "fdr", _Fdr(krx=_krx_404, etf=_etf_df))
    result = K.run_kr_ticker_master_collector(data_dir=str(tmp_path))
    check(result is None, "파일이 없어도 반쪽짜리를 새로 만들지 않음")
    check(sorted(p.name for p in tmp_path.iterdir()) == [], "tmp 폴더에 아무 파일도 안 생김", f"({list(tmp_path.iterdir())})")


# ─────────────────────────────────────────────────────────────────────────────
# ② 실패가 사람에게 드러나는가 — 기록 → 상태 → 문장 → ::warning → metadata → 화면
# ─────────────────────────────────────────────────────────────────────────────
def test_failure_is_recorded_and_worded_for_humans(monkeypatch, tmp_path, capsys):
    path, _ = _seed_existing_master(tmp_path, generated_at="2026-09-07 16:11")
    monkeypatch.setattr(K, "fdr", _Fdr(krx=_krx_404, etf=_etf_df))
    K.run_kr_ticker_master_collector(data_dir=str(tmp_path))

    today = datetime(2026, 9, 8, 16, 11)
    status = K.ticker_master_status(path=str(path), now_kst=today)
    check(status["refresh_attempted"] is True and status["refresh_written"] is False, "기록: 시도했고 못 썼음", f"({status})")
    check(status["refresh_failed_sources"] == ["STOCK"], "기록: 실패 원천 STOCK")
    check("404" in (status["refresh_reason"] or ""), "기록: 사유에 404")
    check(status["generated_date"] == "2026-09-07" and status["age_days"] == 1 and status["is_today"] is False,
          "상태: 어제 파일(1일 전)임을 사실대로", f"({status})")

    notice = data_sanity.ticker_master_notice(status)
    check(bool(notice), "사람에게 보여줄 문장이 만들어짐")
    check("갱신 실패" in notice and "STOCK" in notice and "404" in notice, "문장에 실패·원천·사유가 전부", f"({notice})")
    check("2026-09-07" in notice and "1일 전" in notice, "문장에 마스터 날짜·나이", f"({notice})")
    check("기존 파일을 유지" in notice, "문장에 '덮어쓰지 않고 유지했다'가 명시")

    # 로그 + GitHub Actions 실행 요약(::warning) — 잡이 초록불이어도 요약 화면에서 보이게
    monkeypatch.setattr(K, "get_ticker_master_generated_date", lambda p=None: "2026-09-07")
    monkeypatch.setattr(K, "_now_kst", lambda: today)
    capsys.readouterr()
    K._warn_ticker_master_staleness()
    out = capsys.readouterr().out
    check("🚨" in out and "갱신 실패" in out, "수집기 로그에 🚨 로 찍힘", f"({out!r})")
    check("::warning title=" in out and "갱신 실패" in out.split("::warning")[1], "Actions ::warning 주석으로도 나감")


def test_main_block_exception_path_is_recorded_too():
    """run_kr_ticker_master_collector() 가 예상 밖 예외로 빠져나와도 '못 씀' 이 기록돼야 합니다."""
    src = (REPO_ROOT / "collector_kospi200.py").read_text(encoding="utf-8")
    main_block = src.split('if __name__ == "__main__":')[1]
    after_call = main_block.split("run_kr_ticker_master_collector()")[1][:1200]
    check("_note_ticker_master_refresh(attempted=True, written=False" in after_call,
          "__main__ 의 except 가지에서도 갱신 실패를 기록함")
    # 주석에도 같은 이름이 나오므로 **실제 호출 줄**(주석 아닌 줄)만 봅니다.
    code_lines = [ln for ln in main_block.splitlines() if not ln.strip().startswith("#")]
    def _line_of(call):
        return next(i for i, ln in enumerate(code_lines) if ln.strip().startswith(call))
    check(_line_of("run_kr_ticker_master_collector()") < _line_of("_warn_ticker_master_staleness()")
          < _line_of("run_kospi200_collector()"),
          "순서: 마스터 갱신 → 신선도 경고 → 코스피 수집 (경고가 실패 기록을 본 뒤에 찍힘)")


def test_snapshot_metadata_carries_ticker_master_status(monkeypatch, tmp_path):
    """코스피 스냅샷 metadata.ticker_master 에 같은 판정이 실려야 화면이 읽을 수 있습니다."""
    from test_naver_source_switch import _run_collector_with_everything_faked  # 이미 있는 헬퍼 재사용(§0-3-10)

    K._note_ticker_master_refresh(attempted=True, written=False, failed_sources=["STOCK"],
                                  reason="StockListing('KRX') 실패: HTTPError: HTTP Error 404: Not Found")
    monkeypatch.delenv("NAVER_SOURCE", raising=False)
    payload, _calls, path = _run_collector_with_everything_faked(monkeypatch, tmp_path, {})
    block = payload["metadata"].get("ticker_master")
    check(isinstance(block, dict), "metadata.ticker_master 블록이 있음", f"({payload['metadata'].keys()})")
    check(block.get("refresh_attempted") is True and block.get("refresh_written") is False, "블록에 갱신 실패가 그대로", f"({block})")
    check(block.get("refresh_failed_sources") == ["STOCK"] and "404" in (block.get("refresh_reason") or ""),
          "블록에 원천·사유가 그대로")
    check(str(path).startswith(str(tmp_path)), "🔴 스냅샷도 tmp 에만 씀")
    # 화면이 그 블록으로 문장을 만들 수 있어야 함(JSON 왕복 뒤에도)
    roundtrip = json.loads(json.dumps(block))
    check("갱신 실패" in (data_sanity.ticker_master_notice(roundtrip) or ""), "JSON 왕복 뒤에도 같은 문장")


def test_screen_reads_the_notice_from_metadata():
    """화면(pegy_page)은 판정을 새로 하지 않고 metadata 를 data_sanity.ticker_master_notice 에 넘겨 배너만 띄웁니다."""
    page = (REPO_ROOT / "web" / "pages" / "pegy_page.py").read_text(encoding="utf-8")
    check('data_sanity.ticker_master_notice(metadata.get("ticker_master"))' in page,
          "pegy_page 가 metadata.ticker_master 를 data_sanity.ticker_master_notice 에 넘김")
    seg = page.split('data_sanity.ticker_master_notice(metadata.get("ticker_master"))')[1][:600]
    check("warning_banner(" in seg, "그 문장을 warning_banner 로 띄움")
    check("age_days" not in page and "refresh_failed_sources" not in page,
          "화면이 판정 필드를 직접 해석하지 않음(판정은 한 곳 — §0-3-10)")


def test_notice_when_master_is_days_old():
    """갱신 실패가 여러 날 이어지면(FDR 장기 장애) 며칠 전 것인지 사람이 알아야 합니다."""
    status = {"generated_date": "2026-09-05", "today": "2026-09-08", "age_days": 3, "is_today": False,
              "refresh_attempted": False, "refresh_written": False, "refresh_failed_sources": [], "refresh_reason": None}
    notice = data_sanity.ticker_master_notice(status)
    check(notice is not None and "3일 전" in notice and "오늘 자가 아닙니다" in notice, "며칠 전 파일인지 문장에", f"({notice})")
    check(data_sanity.ticker_master_notice(None) is None, "형식 모르면 None(지어내지 않음)")
    missing = dict(status, generated_date=None, age_days=None)
    check("읽지 못했습니다" in (data_sanity.ticker_master_notice(missing) or ""), "파일 없음도 문장으로")


# ─────────────────────────────────────────────────────────────────────────────
# ③ 평소 날 — 둘 다 성공하면 예전과 똑같이 저장
# ─────────────────────────────────────────────────────────────────────────────
def test_normal_day_writes_file_exactly_like_before(monkeypatch, tmp_path):
    path, before = _seed_existing_master(tmp_path)
    monkeypatch.setattr(K, "fdr", _Fdr(krx=lambda: _krx_df(5), etf=lambda: _etf_df(3)))
    fixed_now = datetime(2026, 9, 8, 16, 11)
    monkeypatch.setattr(K, "_now_kst", lambda: fixed_now)

    result = K.run_kr_ticker_master_collector(data_dir=str(tmp_path))
    check(result == str(path), "정상이면 파일 경로 반환", f"({result})")
    check(hashlib.sha256(path.read_bytes()).hexdigest() != before, "파일이 새 내용으로 바뀜")
    payload = json.loads(path.read_text(encoding="utf-8"))
    types = [s["type"] for s in payload["stocks"]]
    check(types.count("STOCK") == 5 and types.count("ETF") == 3, "주식 5 + ETF 3 이 합쳐짐", f"({types})")
    check(payload["metadata"]["count"] == 8 and payload["metadata"]["generated_at"] == "2026-09-08 16:11",
          "metadata.count·generated_at 이 예전 형식 그대로", f"({payload['metadata']})")
    check({"code", "name", "market", "type"} == set(payload["stocks"][0]), "행 형식(code/name/market/type) 그대로")
    check(not (tmp_path / f".{MASTER}.tmp").exists(), "임시 파일은 바꿔치기 뒤 남지 않음")

    status = K.ticker_master_status(path=str(path), now_kst=fixed_now)
    check(status["refresh_written"] is True and status["is_today"] is True and status["age_days"] == 0,
          "상태: 오늘 자·새로 씀", f"({status})")
    check(data_sanity.ticker_master_notice(status) is None, "정상인 날은 배너 문장 없음(조용)")


def test_fdr_not_installed_is_recorded_not_crashing(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "HAS_FDR", False)
    check(K.run_kr_ticker_master_collector(data_dir=str(tmp_path)) is None, "FDR 미설치면 None")
    rec = K.ticker_master_status(path=str(tmp_path / MASTER))
    check(rec["refresh_attempted"] and not rec["refresh_written"] and "미설치" in (rec["refresh_reason"] or ""),
          "미설치도 '못 씀' 으로 기록", f"({rec})")


def main():
    from _test_discovery import discover_and_run_module_tests
    discover_and_run_module_tests(sys.modules[__name__])
    print("✅ 전체 통과")


if __name__ == "__main__":
    main()
