"""naver-search-mcp `search_news` → NewsItem (F11·D13 ④).

**공시로 설명되지 않는 종목만** 부른다 — 등급이 `none`일 때. 수주·실적은 공시로 나오므로
그때 뉴스를 찾는 것은 노이즈만 늘린다 (아이디어 §2-2).

응답 정제가 이 모듈의 일이다 (2026-08-29 실호출 확인):
- `title`·`description`에 검색어 강조 **`<b>` 태그**와 HTML 엔티티(`&amp;` `&quot;`)가 섞여 온다
- `pubDate`는 RFC 822 (`Fri, 28 Aug 2026 17:30:00 +0900`)
- `link`(네이버 뉴스)와 `originallink`(언론사 원문)가 따로 온다 — 둘 다 남긴다

**검색어에 `주가`를 붙인다** (2026-08-29 A/B 실측). 종목명만 넣으면 일반명사 이름에서 무너진다 —
`핑거` 3건이 전부 핑거푸드·음악 기사였고, `주가`를 붙이자 전환사채 취득 기사가 잡혔다.
`가비아`도 2/3 → 3/3이 됐다. 그래도 완벽하지 않다(2글자 이름 `DL`은 여전히 시황 기사) —
**동음이의 노이즈는 v1에서 걸러내지 않는다** (R17). 사실만 나열하고 판단은 사용자 몫이며,
링크가 옆에 있어 5초면 확인된다.
"""

from __future__ import annotations

import html
import re
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from briefing import mcpc
from briefing.models import NewsItem

TIMEOUT = 20.0
DISPLAY = 5  # 종목당 최대 건수. 늘리면 요약 입력과 메일이 길어진다
SORT = "date"  # 최신순 — 신호가 난 날 근처의 움직임을 본다
QUERY_SUFFIX = "주가"  # 종목명만으로는 동음이의가 섞인다 (실측)

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class _Server(Protocol):
    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = ...
    ) -> Any: ...


def clean_text(raw: str) -> str:
    """`<b>` 태그를 떼고 HTML 엔티티를 풀고 공백을 하나로 줄인다."""
    return _WS.sub(" ", html.unescape(_TAG.sub("", raw))).strip()


def parse_pub_date(raw: str) -> date | None:
    """RFC 822 날짜 → date. 파싱할 수 없으면 None (뉴스를 버리지는 않는다)."""
    if not raw.strip():
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


def parse_news(payload: dict[str, Any]) -> list[NewsItem]:
    """`search_news` 응답 → NewsItem 목록. 제목이나 링크가 없는 항목은 버린다."""
    out: list[NewsItem] = []
    for raw in payload.get("items") or []:
        title, link = clean_text(str(raw.get("title", ""))), str(raw.get("link", "")).strip()
        if not title or not link:
            continue
        out.append(
            NewsItem(
                title=title,
                link=link,
                origin=str(raw.get("originallink", "")).strip(),
                published=parse_pub_date(str(raw.get("pubDate", ""))),
            )
        )
    return out


def query_for(company_name: str) -> str:
    """종목명 → 검색어. `주가`를 붙여 동음이의를 줄인다."""
    return f"{company_name} {QUERY_SUFFIX}".strip()


def fetch_news(company_name: str, *, server: _Server | None = None) -> list[NewsItem]:
    """종목의 최신 뉴스 최대 `DISPLAY`건. 실패는 `mcpc.McpError`로 올린다 (호출자가 생략)."""
    srv = server or mcpc.get("naver")
    args = {"query": query_for(company_name), "display": DISPLAY, "sort": SORT}
    return parse_news(srv.call_json("search_news", args, timeout=TIMEOUT))
