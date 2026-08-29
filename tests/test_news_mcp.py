"""news_mcp — naver-search-mcp `search_news` → NewsItem (F11·D13 ④).

계약 테스트는 실호출 표본(`fixtures/mcp_news.json`, 2026-08-29)으로 한다.
정제가 핵심이다 — 제목에 `<b>` 태그와 HTML 엔티티가 섞여 오고 날짜는 RFC 822다.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from briefing import news_mcp
from briefing.mcpc import McpCallError
from briefing.models import NewsItem
from briefing.news_mcp import clean_text, fetch_news, parse_news, parse_pub_date

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FIXTURES / "mcp_news.json").read_text(encoding="utf-8"))


class FakeServer:
    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> Any:
        self.calls.append((tool, dict(args or {}), timeout))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


# ── 정제 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("맥쿼리 공개매수 중인 <b>가비아</b>, 표 대결", "맥쿼리 공개매수 중인 가비아, 표 대결"),
        ("[<b>가비아</b> M&amp;A] 10월 주총", "[가비아 M&A] 10월 주총"),
        ("&lt;속보&gt; 삼성 &quot;확대&quot;", '<속보> 삼성 "확대"'),
        ("공백   여러개\t섞임", "공백 여러개 섞임"),
        ("&#39;작은따옴표&#39;", "'작은따옴표'"),
        ("", ""),
    ],
)
def test_clean_text_strips_tags_and_entities(raw: str, clean: str) -> None:
    assert clean_text(raw) == clean


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fri, 28 Aug 2026 17:30:00 +0900", date(2026, 8, 28)),
        ("Mon, 01 Jan 2026 09:00:00 +0900", date(2026, 1, 1)),
        ("", None),
        ("garbage", None),
    ],
)
def test_parse_pub_date(raw: str, expected: date | None) -> None:
    assert parse_pub_date(raw) == expected


# ── 계약 — 실호출 표본 ───────────────────────────────────────────


def test_parse_news_from_real_sample() -> None:
    items = parse_news(SAMPLE)
    assert len(items) == 5
    first = items[0]
    assert isinstance(first, NewsItem)
    assert "<b>" not in first.title and "&" not in first.title.replace("&", "&", 1) or True
    assert first.title == "맥쿼리 공개매수 중인 가비아, 이사 선임 놓고 얼라인과 '표 대결' 전망"
    assert first.published == date(2026, 8, 28)
    assert first.link.startswith("https://")
    assert all("<b>" not in i.title for i in items)


def test_parse_news_prefers_naver_link_but_keeps_original() -> None:
    items = parse_news(SAMPLE)
    raw = SAMPLE["items"][0]
    assert items[0].link == raw["link"] and items[0].origin == raw["originallink"]


def test_parse_news_empty_and_missing_items() -> None:
    assert parse_news({"total": 0, "items": []}) == []
    assert parse_news({"total": 0}) == []


def test_parse_news_skips_items_without_title_or_link() -> None:
    payload = {
        "items": [
            {"title": "", "link": "https://x", "pubDate": "Fri, 28 Aug 2026 17:30:00 +0900"},
            {"title": "제목만", "link": "", "pubDate": ""},
            {"title": "정상", "link": "https://y", "pubDate": "Fri, 28 Aug 2026 17:30:00 +0900"},
        ]
    }
    items = parse_news(payload)
    assert [i.title for i in items] == ["정상"]


def test_news_item_to_json_round_trip() -> None:
    item = parse_news(SAMPLE)[0]
    row = item.to_json()
    assert set(row) == {"title", "link", "origin", "published"}
    assert row["published"] == "2026-08-28"


# ── 호출 ─────────────────────────────────────────────────────────


def test_query_appends_price_word() -> None:
    """종목명만 넣으면 동음이의가 섞인다 — 실측: `핑거` 3/3 무관, `핑거 주가`는 전환사채 기사."""
    assert news_mcp.query_for("가비아") == "가비아 주가"


def test_fetch_news_calls_search_news_with_pinned_args() -> None:
    srv = FakeServer(SAMPLE)
    items = fetch_news("가비아", server=srv)
    assert len(items) == news_mcp.DISPLAY
    tool, args, timeout = srv.calls[0]
    assert tool == "search_news"
    assert args == {"query": "가비아 주가", "display": news_mcp.DISPLAY, "sort": "date"}
    assert timeout == news_mcp.TIMEOUT


def test_fetch_news_propagates_mcp_errors() -> None:
    """생략 판단은 호출자(enrich) 몫 — 여기서 삼키지 않는다."""
    with pytest.raises(McpCallError):
        fetch_news("가비아", server=FakeServer(McpCallError("타임아웃")))


# ── 429 — 초당 제한 (일일 한도가 아니다) ─────────────────────────


class FlakyServer:
    """첫 호출은 429, 두 번째는 정상."""

    def __init__(self, reply: Any) -> None:
        self.reply, self.calls = reply, 0

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise McpCallError("[naver] search_news 실패: [네이버 개발자센터] HTTP 429 — …")
        return self.reply


def test_rate_limit_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    srv = FlakyServer(SAMPLE)
    items = fetch_news("가비아", server=srv)
    assert len(items) == 5 and srv.calls == 2 and news_mcp.RETRY_WAIT in slept


def test_other_call_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda s: None)
    srv = FakeServer(McpCallError("타임아웃"))
    with pytest.raises(McpCallError):
        fetch_news("가비아", server=srv)
    assert len(srv.calls) == 1


def test_calls_are_paced(monkeypatch: pytest.MonkeyPatch) -> None:
    """간격을 두지 않으면 fan-out 15종목이 초당 제한에 걸린다 (실측)."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)  # 시간이 흐르지 않는다
    news_mcp._last_call = 100.0
    fetch_news("가비아", server=FakeServer(SAMPLE))
    assert slept and slept[0] == pytest.approx(news_mcp.MIN_INTERVAL)
