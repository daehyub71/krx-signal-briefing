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
        "news": {"with": 0, "none_level": 3},
    }


def test_run_detail_tallies_anomaly_verdicts() -> None:
    bs = [
        briefing(anomaly=Anomaly(score=0, verdict="clean")),
        briefing(anomaly=Anomaly(score=70, verdict="warning")),
        briefing(anomaly=Anomaly(score=1, verdict="clean")),
    ]
    assert enrich.run_detail(bs)["anomaly_verdicts"] == {"clean": 2, "warning": 1}


# ── ④ 뉴스 — 등급 none인 종목만 (F11·D13 ④) ─────────────────────

import pytest  # noqa: E402

from briefing import dart, dart_mcp, mcpc, news_mcp  # noqa: E402
from briefing.models import Disclosure, NewsItem  # noqa: E402

SIG = SignalRow(d=D, strategy="mtf", ticker="079940", name="가비아")
QUARTERLY = Disclosure(rcept_dt=D, report_nm="분기보고서 (2026.03)", rcept_no="1", flr_nm="가비아")
CB = Disclosure(
    rcept_dt=D, report_nm="주요사항보고서(전환사채권발행결정)", rcept_no="2", flr_nm="가비아"
)
NEWS = [
    NewsItem(title="맥쿼리 공개매수 중인 가비아", link="https://n.news.naver.com/x", published=D)
]


class Spy:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kw: object) -> object:
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, Spy]:
    spies = {
        "mcp": Spy([QUARTERLY]),  # 기본: 공시는 있으나 아무것도 안 걸림 → none
        "anomaly": Spy(None),
        "insider": Spy(None),
        "news": Spy(NEWS),
    }
    monkeypatch.setattr(dart_mcp, "fetch_disclosures", spies["mcp"])
    monkeypatch.setattr(dart_mcp, "fetch_anomaly", spies["anomaly"])
    monkeypatch.setattr(dart_mcp, "fetch_insider", spies["insider"])
    monkeypatch.setattr(news_mcp, "fetch_news", spies["news"])
    monkeypatch.setattr(dart, "fetch_disclosures", Spy([]))
    return spies


def test_news_fetched_only_for_none_level(sources: dict[str, Spy]) -> None:
    """공시로 설명되지 않는 종목만 — 등급 none일 때만 부른다 (D13 ④)."""
    b = enrich.briefing_for(SIG, "00506294", D, D)
    assert b.level == "none" and b.news == tuple(NEWS)
    assert sources["news"].calls == [("가비아",)]


def test_news_is_fetched_for_flagged_stocks_too(sources: dict[str, Spy]) -> None:
    """v2.0은 등급 `none`인 종목만 불렀다. **가장 값진 뉴스가 🔴 종목에서 나왔다** —
    씨피시스템 CB의 자금 용도("전액 제2공장 시설투자")는 공시 제목에도 규칙표에도 없다
    (2026-08-30 실측). D16으로 전 종목에 붙인다."""
    sources["mcp"].result = [CB]
    b = enrich.briefing_for(SIG, "00506294", D, D)
    assert b.level == "red"
    assert sources["news"].calls, "위험 종목에도 뉴스를 부른다"


def test_news_failure_is_skipped_not_fatal(sources: dict[str, Spy]) -> None:
    """뉴스는 있으면 좋은 층 — 실패하면 생략 표기만 남기고 메일은 간다."""
    sources["news"].result = mcpc.McpStartError("[naver] 환경변수 없음")
    b = enrich.briefing_for(SIG, "00506294", D, D)
    assert b.level == "none" and b.news == () and "news" in b.skipped


def test_news_empty_result_is_not_a_skip(sources: dict[str, Spy]) -> None:
    """검색 결과가 0건인 것과 층이 죽은 것은 다르다."""
    sources["news"].result = []
    b = enrich.briefing_for(SIG, "00506294", D, D)
    assert b.news == () and "news" not in b.skipped


def test_run_detail_counts_news() -> None:
    bs = [
        briefing(level="none", news=(NEWS[0],)),
        briefing(level="none", skipped=("news",)),
        briefing(level="red"),
    ]
    detail = enrich.run_detail(bs)
    assert detail["news"] == {"with": 1, "none_level": 2}
    assert detail["skipped"]["news"] == 1
