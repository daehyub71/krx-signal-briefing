"""종목 하나의 공시·보조 신호 수집 — MCP 우선, REST 폴백, 보조는 개별 생략 (SPEC F4·F4b·D15).

I/O 층이다. `fetch_one` 노드가 20줄을 지키도록 호출 순서와 실패 처리를 여기로 모았다.

| 단계 | 소스 (korean-dart-mcp) | 실패하면 |
|------|------------------------|----------|
| 공시 | `search_disclosures` | REST(`dart.py`)로 **폴백** — 그것도 실패하면 예외(종목 `error`) |
| anomaly | `disclosure_anomaly` | 생략 (`skipped`에 기록) — 등급을 바꾸지 않는 참고값 |
| insider | `insider_signal` | 생략 — 있으면 매도 군집에 🟡 |
| 뉴스 | naver-search-mcp `search_news` — **등급 `none`일 때만** | 생략 (`skipped`에 기록) |

생략은 조용히 하지 않는다 — `Briefing.skipped`에 남기고 본문에 `⚠ 보조 신호 생략`,
`ksb_runs.detail`에 집계한다.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from briefing import dart, dart_mcp, flags, mcpc, news_mcp
from briefing.models import (
    Anomaly,
    Briefing,
    Disclosure,
    EventBody,
    Flag,
    Flow,
    Insider,
    NewsItem,
    SignalRow,
)

# 보조 신호에서 "생략"으로 삼키는 예외. 그 밖(프로그래밍 오류)은 그대로 올린다.
SIDE_SKIP = (mcpc.McpError, ValueError, KeyError, TypeError)


def disclosures_with_fallback(corp_code: str, bgn: date, end: date) -> tuple[list[Disclosure], str]:
    """공시 목록. MCP가 실패하면 REST로 폴백한다.

    Returns:
        `(공시 목록, 출처)` — 출처는 `"mcp"` 또는 `"rest"`.

    Raises:
        dart.DartError: MCP도 REST도 실패했을 때 (호출자가 종목을 `error`로 표시한다).
    """
    try:
        return dart_mcp.fetch_disclosures(corp_code, bgn, end), "mcp"
    except mcpc.McpError as exc:
        print(f"[enrich] {corp_code} MCP 공시 실패 → REST 폴백: {exc}")
        return dart.fetch_disclosures(corp_code, bgn, end), "rest"


def side_signals(
    corp_code: str, bgn: date, end: date
) -> tuple[Anomaly | None, Insider | None, tuple[str, ...]]:
    """보조 신호 둘. 각각 따로 실패하고 따로 생략된다.

    Returns:
        `(anomaly, insider, 생략된 이름들)`.
    """
    skipped: list[str] = []
    anomaly: Anomaly | None = None
    insider: Insider | None = None
    try:
        anomaly = dart_mcp.fetch_anomaly(corp_code)
    except SIDE_SKIP as exc:
        skipped.append("anomaly")
        print(f"[enrich] {corp_code} anomaly 생략: {exc}")
    try:
        insider = dart_mcp.fetch_insider(corp_code, bgn, end)
    except SIDE_SKIP as exc:
        skipped.append("insider")
        print(f"[enrich] {corp_code} insider 생략: {exc}")
    return anomaly, insider, tuple(skipped)


def news_for(company_name: str) -> tuple[tuple[NewsItem, ...], bool]:
    """등급 `none`인 종목의 뉴스 (F11). 실패는 생략으로 삼킨다.

    Returns:
        `(뉴스, 생략됐는가)`. 검색 결과 0건과 층이 죽은 것은 다르다 — 후자만 `skipped`에 남는다.
    """
    try:
        return tuple(news_mcp.fetch_news(company_name)), False
    except SIDE_SKIP as exc:
        print(f"[enrich] {company_name} 뉴스 생략: {exc}")
        return (), True


def event_bodies(
    corp_code: str, flag_list: Sequence[Flag], bgn: date, end: date
) -> tuple[EventBody, ...]:
    """플래그된 공시의 본문 (F15). 규칙 종류마다 한 번씩 부른다.

    **정형 공시의 본문은 부르지 않는다** — 규칙에 걸린 것만이다. 08/26 기준 5건이었다.
    실패는 생략으로 삼킨다: 본문은 있으면 좋은 층이고, 없으면 제목만 쓴다 (D15).

    Args:
        corp_code: DART 고유번호.
        flag_list: 그 종목의 플래그.
        bgn: 조회 창 시작.
        end: 조회 창 끝.

    Returns:
        본문 목록. 플래그된 접수번호에 해당하는 것만 남긴다 — 같은 창의 다른 건이 섞이지 않게.
    """
    wanted = {f.rcept_no for f in flag_list}
    rules = {f.rule for f in flag_list}
    out: list[EventBody] = []
    for rule in sorted(rules):
        try:
            out.extend(dart_mcp.fetch_event(corp_code, rule, bgn, end))
        except SIDE_SKIP as exc:
            print(f"[enrich] {corp_code} {rule} 본문 생략: {exc}")
    return tuple(b for b in out if b.rcept_no in wanted)


def briefing_for(
    signal: SignalRow,
    corp_code: str,
    bgn: date,
    end: date,
    *,
    flow: Flow | None = None,
    flow_skipped: bool = False,
) -> Briefing:
    """종목 하나의 브리핑 — ① 공시(폴백) → ② 판정 → ③ 보조 신호·시세 → ④ 뉴스. `fetch_one`이 부른다.

    시세(`flow`)는 `load_market`이 배치 1회로 받아 둔 것을 받기만 한다 (F12).
    뉴스(④)는 **등급이 `none`일 때만** 부른다 — 공시가 이미 설명하는 종목에 뉴스는 노이즈다 (D13 ④).

    Raises:
        dart.DartError: 공시를 어느 경로로도 못 받았을 때. 보조 신호는 그 전에 부르지 않는다.
    """
    raw, source = disclosures_with_fallback(corp_code, bgn, end)
    anomaly, insider, skipped = side_signals(corp_code, bgn, end)
    if flow_skipped:
        skipped = (*skipped, "flow")
    v = flags.classify(raw, company_name=signal.name, insider=insider)
    # **전 종목에 붙인다** (F11 v2 · D16, v3.0). v2.0은 등급 `none`인 종목만 불렀는데,
    # 가장 값진 뉴스가 🔴 종목에서 나왔다 — 씨피시스템 CB의 자금 용도("전액 제2공장 시설투자")는
    # 공시 제목에도 없고 우리 규칙표에도 없다 (2026-08-30 실측).
    news, news_skipped = news_for(signal.name)
    if news_skipped:
        skipped = (*skipped, "news")
    bodies = event_bodies(corp_code, v.flags, bgn, end)
    return Briefing.from_signal(
        signal,
        corp_code,
        v.level,
        flags=v.flags,
        disclosures=v.disclosures,
        anomaly=anomaly,
        insider=insider,
        flow=flow,
        news=news,
        bodies=bodies,
        source=source,
        skipped=skipped,
    )


def run_detail(briefings: Iterable[Briefing]) -> dict[str, Any]:
    """`ksb_runs.detail`용 집계 — 출처 · 생략 · anomaly verdict · 뉴스. 순수 함수."""
    source: collections.Counter[str] = collections.Counter()
    skipped: collections.Counter[str] = collections.Counter()
    verdicts: collections.Counter[str] = collections.Counter()
    with_news = none_level = 0
    for b in briefings:
        source[b.source if b.corp_code is not None and b.level != "error" else "none"] += 1
        skipped.update(b.skipped)
        if b.anomaly is not None:
            verdicts[b.anomaly.verdict] += 1
        if b.news:
            with_news += 1
        if b.level == "none":
            none_level += 1
    return {
        "source": dict(source),
        "skipped": dict(skipped),
        "anomaly_verdicts": dict(verdicts),
        "news": {"with": with_news, "none_level": none_level},
    }
