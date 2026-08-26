"""main — CLI 인자 · 종료 코드 · --if-not-briefed 경로. 그래프와 DB는 전부 스텁."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from briefing import config, store
from briefing import main as m
from briefing.nodes import BriefingRunError
from briefing.state import STATUS_OK


def test_parse_date_default_is_today() -> None:
    assert m.parse_date(None) == date.today()


def test_parse_date_yyyymmdd() -> None:
    assert m.parse_date("20260825") == date(2026, 8, 25)


def test_parser_defaults() -> None:
    a = m.build_parser().parse_args([])
    assert a.date is None and a.dry_run is False and a.force is False
    assert a.if_not_briefed is False


def test_parser_all_flags() -> None:
    argv = ["--date", "20260825", "--dry-run", "--force", "--if-not-briefed"]
    a = m.build_parser().parse_args(argv)
    assert a.date == "20260825" and a.dry_run and a.force and a.if_not_briefed


class FakeGraph:
    """invoke()가 받은 초기 상태를 기록하고 정해진 결과를 돌려준다."""

    def __init__(self, result: dict[str, Any] | None = None, raise_: Exception | None = None):
        self.result = result or {"status": STATUS_OK, "signals": [], "briefings": []}
        self.raise_ = raise_
        self.received: dict[str, Any] | None = None

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self.received = state
        if self.raise_:
            raise self.raise_
        return self.result


@pytest.fixture
def no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """env·DB 연결을 전부 막는다."""
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(store, "close", lambda: None)


def test_main_injects_run_date_and_flags(no_io: None, monkeypatch: pytest.MonkeyPatch) -> None:
    g = FakeGraph()
    monkeypatch.setattr(m, "build_graph", lambda: g)
    assert m.main(["--date", "20260825", "--dry-run", "--force"]) == 0
    assert g.received is not None
    assert g.received["run_date"] == date(2026, 8, 25)
    assert g.received["dry_run"] is True and g.received["force"] is True


def test_main_returns_1_on_run_error(no_io: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """finalize가 올린 예외는 종료 코드 1로 — 워크플로가 실패해야 한다 (N5)."""
    monkeypatch.setattr(m, "build_graph", lambda: FakeGraph(raise_=BriefingRunError("x")))
    assert m.main(["--dry-run"]) == 1


def test_main_if_not_briefed_skips_graph_when_already_run(
    no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """예비 cron 경로 — 오늘 이미 돌았으면 그래프를 만들지도 않고 0으로 끝난다 (F0)."""
    monkeypatch.setattr(store, "conn", lambda: object())
    monkeypatch.setattr(store, "briefed_today", lambda conn, d: True)
    called = {"n": 0}

    def build() -> FakeGraph:
        called["n"] += 1
        return FakeGraph()

    monkeypatch.setattr(m, "build_graph", build)
    assert m.main(["--if-not-briefed"]) == 0
    assert called["n"] == 0


def test_main_if_not_briefed_runs_when_not_yet(
    no_io: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "conn", lambda: object())
    monkeypatch.setattr(store, "briefed_today", lambda conn, d: False)
    g = FakeGraph()
    monkeypatch.setattr(m, "build_graph", lambda: g)
    assert m.main(["--if-not-briefed"]) == 0
    assert g.received is not None
