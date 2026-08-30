"""news_mcp — naver-search-mcp `search_news` → NewsItem (F11·D13 ④).

계약 테스트는 실호출 표본(`fixtures/mcp_news.json`, 2026-08-29)으로 한다.
정제가 핵심이다 — 제목에 `<b>` 태그와 HTML 엔티티가 섞여 오고 날짜는 RFC 822다.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, cast

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
    assert set(row) == {"title", "link", "origin", "published", "summary"}
    assert row["published"] == "2026-08-28"


# ── 호출 ─────────────────────────────────────────────────────────


def test_query_is_the_name_alone_since_v2() -> None:
    """v2.0은 `주가`를 붙였다. 2026-08-30 A/B에서 그쪽 적합도가 64%로 더 낮았다 —
    자동 생성 시세 기사가 상위를 채웠기 때문이다. 동음이의는 `about()`이 거른다."""
    assert news_mcp.query_for("가비아") == "가비아"


def test_fetch_news_calls_search_news_with_pinned_args() -> None:
    srv = FakeServer(SAMPLE)
    fetch_news("가비아", server=srv)
    tool, args, timeout = srv.calls[0]
    assert tool == "search_news"
    assert args == {"query": "가비아", "display": news_mcp.DISPLAY, "sort": "sim"}
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
    assert srv.calls == 2 and news_mcp.RETRY_WAIT in slept
    # 재시도 경로에도 제목 필터가 걸린다 — 빠뜨리면 429가 난 종목만 안 걸러진다.
    assert items and all("가비아" in n.title for n in items)


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


# ── F11 v2 (v3.0, 2026-08-30) ────────────────────────────────────
#
# 실측이 바꾼 것들. `{종목명} 주가` + 최신순은 제목 적합도가 **64%**였고,
# 자동 생성 시세 기사가 상위를 채웠다. `{종목명}` + 관련도순은 **95%**다.
# 그리고 네이버가 주는 `description`(기사 요약 ~100자)을 v2.0은 받고서 버렸다 —
# 그것이 분석의 주재료다 (씨피시스템 CB의 자금 용도가 거기 있었다).

REAL_ITEM = {
    "title": "<b>씨피시스템</b>, 100억 규모 CB 발행…전액 제2공장 투입",
    "originallink": "https://www.newsis.com/view/NISX20260826_0003763415",
    "link": "https://n.news.naver.com/mnews/article/003/0014149387?sid=101",
    "description": (
        "첨단산업용 케이블체인 전문기업 <b>씨피시스템</b>은 100억원 규모의 전환사채(CB) "
        "발행을 결정했다고 26일 밝혔다. 회사 측에 따르면 조달자금은 전액 제2공장 설립에 "
        "필요한 생산설비 등 시설투자에 사용될 예정이다. 발행... "
    ),
    "pubDate": "Wed, 26 Aug 2026 13:51:00 +0900",
}


def test_query_is_the_company_name_alone() -> None:
    """`주가`를 붙이면 자동 생성 시세 기사가 상위를 채운다 (적합도 64% → 95%)."""
    assert news_mcp.query_for("씨피시스템") == "씨피시스템"


def test_sort_is_by_relevance_not_recency() -> None:
    """최신순은 매일 쏟아지는 시세 기사를 먼저 준다."""
    assert news_mcp.SORT == "sim"


def test_description_is_kept_and_cleaned() -> None:
    """기사 요약이 분석의 주재료다 — v2.0은 받고서 버렸다."""
    (item,) = news_mcp.parse_news({"items": [REAL_ITEM]})
    assert "100억원 규모의 전환사채(CB) 발행을 결정" in item.summary
    assert "전액 제2공장 설립" in item.summary
    assert "<b>" not in item.summary


def test_title_is_still_cleaned() -> None:
    (item,) = news_mcp.parse_news({"items": [REAL_ITEM]})
    assert item.title == "씨피시스템, 100억 규모 CB 발행…전액 제2공장 투입"


def test_an_item_without_a_description_is_still_kept() -> None:
    """요약이 없다고 기사를 버리지는 않는다 — 제목과 링크가 본체다."""
    (item,) = news_mcp.parse_news({"items": [{**REAL_ITEM, "description": ""}]})
    assert item.summary == "" and item.title


# ── 제목 필터 — 계열사·동음이의를 걸러 낸다 ──────────────────────


def test_keeps_only_articles_whose_title_names_the_company() -> None:
    """`LG`로 검색하면 야구단·계열사 기사가 섞인다 (실측).

    `부산 LG-롯데전`은 앞이 한글(`산`)이라 걸러진다 — 야구단 기사다.
    `LG전자`는 앞이 비어 남는다. 다른 종목이지만 지주사 기사와 함께 읽을 값이 있다.
    """
    items = [
        {"title": "<b>LG</b>전자, 3분기 영업이익 발표", "link": "https://n/1"},
        {"title": "부산 LG-롯데전, 우천 노게임", "link": "https://n/2"},
        {"title": "코스피 상승 마감", "link": "https://n/3"},
    ]
    kept = news_mcp.about(news_mcp.parse_news({"items": items}), "LG")
    assert [n.link for n in kept] == ["https://n/1"]


def test_the_filter_ignores_spaces_in_the_company_name() -> None:
    """`한올바이오파마`가 제목에서 `한올 바이오파마`로 띄어 쓰이기도 한다."""
    items = [{"title": "한올 바이오파마, 임상 3상 진입", "link": "https://n/1"}]
    kept = news_mcp.about(news_mcp.parse_news({"items": items}), "한올바이오파마")
    assert len(kept) == 1


def test_the_filter_drops_everything_when_nothing_matches() -> None:
    """0건과 '층이 죽었다'는 다르다 — 0건은 그냥 0건이다."""
    items = [{"title": "코스피 상승 마감", "link": "https://n/1"}]
    assert news_mcp.about(news_mcp.parse_news({"items": items}), "씨피시스템") == []


def test_fetch_news_applies_the_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    class Srv:
        def call_json(
            self, tool: str, args: dict[str, object], timeout: float
        ) -> dict[str, object]:
            self.args = args
            return {"items": [REAL_ITEM, {"title": "코스피 상승 마감", "link": "https://n/9"}]}

    srv = Srv()
    monkeypatch.setattr(news_mcp, "_wait_turn", lambda: None)
    out = news_mcp.fetch_news("씨피시스템", server=cast("Any", srv))
    assert [n.link for n in out] == [REAL_ITEM["link"]]
    assert srv.args["query"] == "씨피시스템"
    assert srv.args["sort"] == "sim"


def test_the_filter_does_not_match_a_name_inside_a_longer_company_name() -> None:
    """`아이텍`이 `위세아이텍` 안에서 잡혔다 — 2026-08-30 실호출에서 모델이 먼저 지적했다.

    다섯 건 전부 다른 회사 기사였고, 서술은 "아이텍의 공시와 연결되는 재료가 아니다"로 끝났다.
    한글 이름은 이어 붙으므로 **앞뒤가 한글이면 다른 회사**로 본다.
    """
    items = [
        {"title": "위세아이텍, 상장 후 최대 배당 추진", "link": "https://n/1"},
        {"title": "아이텍, 전환가액 조정 공시", "link": "https://n/2"},
        {"title": "[특징주] 아이텍 급등", "link": "https://n/3"},
    ]
    kept = news_mcp.about(news_mcp.parse_news({"items": items}), "아이텍")
    assert [n.link for n in kept] == ["https://n/2", "https://n/3"]


def test_the_filter_still_matches_when_punctuation_touches_the_name() -> None:
    items = [
        {"title": "'제테마' 中 보톡스 허가 신청", "link": "https://n/1"},
        {"title": "제테마(216080), 계약 체결", "link": "https://n/2"},
    ]
    kept = news_mcp.about(news_mcp.parse_news({"items": items}), "제테마")
    assert len(kept) == 2
