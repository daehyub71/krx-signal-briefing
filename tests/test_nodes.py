"""nodes — I/O 노드의 상태 매핑. store는 전부 스텁."""

from __future__ import annotations

from datetime import date

import pytest

from briefing import nodes, store
from briefing.state import GATE_MISSING, GATE_READY, GATE_STALE, initial_state

RUN_DATE = date(2026, 8, 26)
DATA_DATE = date(2026, 8, 25)


@pytest.fixture
def no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "conn", lambda: object())


def test_gate_ready_when_run_recorded(no_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (DATA_DATE, "ok"))
    out = nodes.gate(initial_state(RUN_DATE))
    assert out == {"gate": GATE_READY, "data_date": DATA_DATE}


@pytest.mark.parametrize("status", ["partial_send_failed", "send_failed"])
def test_gate_ready_even_if_upstream_send_failed(
    no_db: None, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """상위는 저장 후 발송한다 — 발송이 실패해도 신호는 있다 (F1)."""
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (DATA_DATE, status))
    assert nodes.gate(initial_state(RUN_DATE))["gate"] == GATE_READY


def test_gate_stale_when_upstream_had_stale_data(
    no_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (None, "stale_data"))
    out = nodes.gate(initial_state(RUN_DATE))
    assert out["gate"] == GATE_STALE and out["data_date"] is None


def test_gate_missing_when_no_row(no_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: None)
    out = nodes.gate(initial_state(RUN_DATE))
    assert out == {"gate": GATE_MISSING, "data_date": None}
