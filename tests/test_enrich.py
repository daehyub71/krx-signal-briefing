"""enrich — 종목 하나의 공시·보조 신호 수집 오케스트레이션 (I/O 층). 소스는 전부 스텁."""

from __future__ import annotations

from datetime import date

from briefing import enrich
from briefing.models import Anomaly, Briefing, Insider, SignalRow

D = date(2026, 8, 25)


def briefing(**kw: object) -> Briefing:
    base: dict[str, object] = {
        "signal": SignalRow(d=D, strategy="mtf", ticker="079940", name="x"),
        "corp_code": "1",
        "level": "none",
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


def test_run_detail_counts_sources_and_skips() -> None:
    """ksb_runs.detail에 남길 집계 — 폴백 몇 건, 무엇을 몇 번 생략했나."""
    bs = [
        briefing(source="mcp", skipped=()),
        briefing(source="rest", skipped=("anomaly", "insider")),
        briefing(source="mcp", skipped=("anomaly",), anomaly=None, insider=Insider(signal="none")),
        briefing(level="unknown", corp_code=None),
    ]
    assert enrich.run_detail(bs) == {
        "source": {"mcp": 2, "rest": 1, "none": 1},
        "skipped": {"anomaly": 2, "insider": 1},
        "anomaly_verdicts": {},
    }


def test_run_detail_tallies_anomaly_verdicts() -> None:
    bs = [
        briefing(anomaly=Anomaly(score=0, verdict="clean")),
        briefing(anomaly=Anomaly(score=70, verdict="warning")),
        briefing(anomaly=Anomaly(score=1, verdict="clean")),
    ]
    assert enrich.run_detail(bs)["anomaly_verdicts"] == {"clean": 2, "warning": 1}
