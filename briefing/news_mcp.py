"""naver-search-mcp `search_news` → NewsItem (F11·D13 ④).

**전 종목에 붙인다** (F11 v2 · D16, v3.0). v2.0은 등급 `none`인 종목만 불렀는데,
가장 값진 뉴스가 🔴 종목에서 나왔다 — 씨피시스템 CB의 자금 용도("전액 제2공장 시설투자")는
공시 제목에도 없고 규칙표에도 없다 (2026-08-30 실측).

응답 정제가 이 모듈의 일이다 (2026-08-29 실호출 확인):
- `title`·`description`에 검색어 강조 **`<b>` 태그**와 HTML 엔티티(`&amp;` `&quot;`)가 섞여 온다
- `pubDate`는 RFC 822 (`Fri, 28 Aug 2026 17:30:00 +0900`)
- `link`(네이버 뉴스)와 `originallink`(언론사 원문)가 따로 온다 — 둘 다 남긴다

**검색어는 종목명만, 정렬은 관련도순** (F11 v2, 2026-08-30 A/B 실측).
v2.0의 `{종목명} 주가` + 최신순은 적합도 **64%**였다 — 매일 자동 생성되는 시세 기사가
상위를 채웠다. 종목명만 + 관련도순이 **95%**다.

동음이의는 검색어가 아니라 **결과**를 좁혀 막는다 (`about()`) — 검색어를 좁히면
정작 필요한 기사도 빠진다. 실수집에서 적합도 100%(52/52)가 나왔다.
"""

from __future__ import annotations

import html
import re
import threading
import time
from collections.abc import Sequence
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from briefing import mcpc
from briefing.models import NewsItem

TIMEOUT = 20.0
DISPLAY = 5  # 종목당 최대 건수. 늘리면 요약 입력과 메일이 길어진다
SORT = "sim"  # 관련도순 (F11 v2). 최신순은 매일 쏟아지는 자동 생성 시세 기사가 상위를 채운다
# 검색어는 **종목명만** 쓴다 (F11 v2, 2026-08-30 A/B 실측).
# `{종목명} 주가` + 최신순: 제목 적합도 64% · `{종목명}` + 관련도순: **95%**.
# 동음이의는 검색어가 아니라 `about()`의 제목 필터로 거른다.

# 네이버는 초당 호출을 제한한다 — fan-out 15종목이 몰리면 HTTP 429가 난다 (2026-08-29 실측).
# 일일 한도(25,000)와는 다른 것이라 간격만 두면 해소된다.
MIN_INTERVAL = 0.35
RETRY_WAIT = 1.5
_pace = threading.Lock()
_last_call = 0.0

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# 한글 음절·자모. 이름 앞뒤가 한글이면 더 긴 회사 이름의 일부다.
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


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
                summary=clean_text(str(raw.get("description", ""))),
            )
        )
    return out


def query_for(company_name: str) -> str:
    """종목명 → 검색어 (F11 v2). **종목명만** 쓴다.

    `주가`를 붙이던 v2.0은 자동 생성 시세 기사(`… 주가, 8월 24일 장중 5,170원 2.78% 상승`)를
    끌어와 적합도가 64%였다. 종목명만 + 관련도순이 95%다 (2026-08-30 A/B 실측).
    """
    return company_name.strip()


def about(items: Sequence[NewsItem], company_name: str) -> list[NewsItem]:
    """제목에 종목명이 없는 기사를 버린다 (F11 v2 — 동음이의·계열사 차단, R17).

    `LG`로 검색하면 야구단(`부산 LG-롯데전`)과 계열사(`LG이노텍 주가`) 기사가 섞인다.
    검색어를 좁히는 대신 **결과를 좁힌다** — 검색어를 좁히면 정작 필요한 기사도 빠진다.

    제목에서 공백을 지우고 비교한다: `한올바이오파마`가 `한올 바이오파마`로 쓰이기도 한다.

    Args:
        items: 파싱된 뉴스.
        company_name: 종목명.

    Returns:
        제목에 종목명이 든 기사만. 0건일 수 있다 — 0건과 "층이 죽었다"는 다르다.
    """
    needle = _WS.sub("", company_name)
    if not needle:
        return []
    return [n for n in items if _names(needle, _WS.sub("", n.title))]


def _names(needle: str, title: str) -> bool:
    """제목이 **그 종목**을 가리키는가.

    단순 부분 문자열이면 `아이텍`이 `위세아이텍` 안에서 잡힌다 — 2026-08-30 실호출에서
    다섯 건 전부 다른 회사 기사였고, 모델이 "아이텍의 공시와 연결되는 재료가 아니다"라고
    먼저 알아봤다. **앞 글자만 본다** — 한국 회사 이름은 앞에 수식어가 붙어 길어지지만
    (`위세아이텍`), 뒷글자는 조사나 서술어인 경우가 많아(`아이텍급등`·`제테마는`)
    막으면 멀쩡한 기사를 버린다.
    """
    start = 0
    while (i := title.find(needle, start)) != -1:
        if i == 0 or not _HANGUL.match(title[i - 1]):
            return True
        start = i + 1
    return False


def _wait_turn() -> None:
    """호출 간 최소 간격을 둔다. fan-out 스레드가 몰려도 초당 제한에 걸리지 않게."""
    global _last_call
    with _pace:
        gap = time.monotonic() - _last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        _last_call = time.monotonic()


def fetch_news(company_name: str, *, server: _Server | None = None) -> list[NewsItem]:
    """종목의 최신 뉴스 최대 `DISPLAY`건. 실패는 `mcpc.McpError`로 올린다 (호출자가 생략).

    HTTP 429(초당 제한)면 한 번 쉬었다 다시 부른다 — 일일 한도가 아니라 속도 문제다.
    """
    srv = server or mcpc.get("naver")
    args = {"query": query_for(company_name), "display": DISPLAY, "sort": SORT}
    _wait_turn()
    try:
        return about(parse_news(srv.call_json("search_news", args, timeout=TIMEOUT)), company_name)
    except mcpc.McpCallError as exc:
        if "429" not in str(exc):
            raise
        print(f"[news] {company_name} 429 — {RETRY_WAIT}초 후 재시도")
        time.sleep(RETRY_WAIT)
        _wait_turn()
        # 재시도 경로에도 같은 필터를 건다 — 빠뜨리면 429가 난 종목만 걸러지지 않는다.
        return about(parse_news(srv.call_json("search_news", args, timeout=TIMEOUT)), company_name)
