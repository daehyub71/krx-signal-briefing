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


# ── fetch_one — 종목 하나: 멱등 · unknown · error · 정상 (F3·F4·F5) ──

from datetime import timedelta  # noqa: E402
from typing import cast  # noqa: E402

from briefing import dart  # noqa: E402
from briefing.models import Briefing, Disclosure, SignalRow  # noqa: E402
from briefing.state import FetchItem  # noqa: E402

SIG = SignalRow(d=DATA_DATE, strategy="mtf", ticker="079940", name="가비아")


def fetch_item(**kw: object) -> FetchItem:
    base: dict[str, object] = {
        "signal": SIG,
        "corp_code": "00506294",
        "existing": None,
        "force": False,
        "run_date": RUN_DATE,
    }
    base.update(kw)
    return cast(FetchItem, base)


class DartSpy:
    """fetch_disclosures 대역 — 인자를 기록하고 정해진 결과/예외를 돌려준다."""

    def __init__(self, result: list[Disclosure] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, date, date]] = []

    def __call__(self, corp_code: str, bgn: date, end: date) -> list[Disclosure]:
        self.calls.append((corp_code, bgn, end))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_fetch_one_reuses_existing_without_dart(monkeypatch: pytest.MonkeyPatch) -> None:
    """그날 브리핑이 이미 있으면 DART를 다시 부르지 않는다 (N6)."""
    spy = DartSpy([])
    monkeypatch.setattr(dart, "fetch_disclosures", spy)
    existing = Briefing.from_signal(SIG, "00506294", "red")
    out = nodes.fetch_one(fetch_item(existing=existing))
    assert out == {"briefings": [existing], "dart_calls": 0} and spy.calls == []


def test_fetch_one_force_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = DartSpy([])
    monkeypatch.setattr(dart, "fetch_disclosures", spy)
    existing = Briefing.from_signal(SIG, "00506294", "red")
    out = nodes.fetch_one(fetch_item(existing=existing, force=True))
    assert len(spy.calls) == 1 and out["briefings"][0].level == "none"


def test_fetch_one_unknown_when_no_corp_code(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = DartSpy([])
    monkeypatch.setattr(dart, "fetch_disclosures", spy)
    out = nodes.fetch_one(fetch_item(corp_code=None))
    b = out["briefings"][0]
    assert b.level == "unknown" and b.corp_code is None and out["dart_calls"] == 0
    assert spy.calls == []


def test_fetch_one_error_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """한 종목의 조회 실패가 fan-out 전체를 죽이면 안 된다 — level='error'로 돌려보낸다."""
    monkeypatch.setattr(
        dart, "fetch_disclosures", DartSpy(dart.DartRateLimitError("020 한도", "020"))
    )
    out = nodes.fetch_one(fetch_item())
    b = out["briefings"][0]
    assert b.level == "error" and "020" in b.error and out["dart_calls"] == 1


def test_fetch_one_classifies_and_uses_window(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        Disclosure(
            rcept_dt=date(2026, 8, 22),
            report_nm="[기재정정]주요사항보고서(전환사채권발행결정)",
            rcept_no="1",
            flr_nm="가비아",
        ),
        Disclosure(
            rcept_dt=date(2026, 8, 7),
            report_nm="분기보고서 (2026.03)",
            rcept_no="2",
            flr_nm="가비아",
        ),
    ]
    spy = DartSpy(items)
    monkeypatch.setattr(dart, "fetch_disclosures", spy)
    out = nodes.fetch_one(fetch_item())
    b = out["briefings"][0]
    assert spy.calls == [("00506294", RUN_DATE - timedelta(days=30), RUN_DATE)]
    assert b.level == "red" and [f.rule for f in b.flags] == ["cb"]
    assert [d.corrected for d in b.disclosures] == [True, False]
    assert b.ticker == "079940" and b.name == "가비아" and b.corp_code == "00506294"
    assert out["dart_calls"] == 1


def test_fetch_one_applies_reit_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    reit = SignalRow(d=DATA_DATE, strategy="mtf", ticker="417310", name="코람코더원리츠")
    items = [
        Disclosure(
            rcept_dt=date(2026, 8, 20),
            report_nm="주요사항보고서(유상증자결정)",
            rcept_no="9",
            flr_nm="코람코더원리츠",
        )
    ]
    monkeypatch.setattr(dart, "fetch_disclosures", DartSpy(items))
    b = nodes.fetch_one(fetch_item(signal=reit, corp_code="00333333"))["briefings"][0]
    assert b.level == "amber"


def test_fetch_one_is_thin() -> None:
    """노드는 20줄을 넘지 않는다 (N11)."""
    import inspect

    body = inspect.getsource(nodes.fetch_one).split('"""')[-1]  # docstring 뒤
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) <= 20, len(lines)
