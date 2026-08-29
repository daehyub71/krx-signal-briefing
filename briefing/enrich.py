"""종목 하나의 공시·보조 신호 수집 — MCP 우선, REST 폴백, 보조는 개별 생략 (SPEC F4·F4b·D15).

I/O 층이다. `fetch_one` 노드가 20줄을 지키도록 호출 순서와 실패 처리를 여기로 모았다.

| 단계 | 소스 (korean-dart-mcp) | 실패하면 |
|------|------------------------|----------|
| 공시 | `search_disclosures` | REST(`dart.py`)로 **폴백** — 그것도 실패하면 예외(종목 `error`) |
| anomaly | `disclosure_anomaly` | 생략 (`skipped`에 기록) — 등급을 바꾸지 않는 참고값 |
| insider | `insider_signal` | 생략 — 있으면 매도 군집에 🟡 |

생략은 조용히 하지 않는다 — `Briefing.skipped`에 남기고 본문에 `⚠ 보조 신호 생략`,
`ksb_runs.detail`에 집계한다.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
from datetime import date
from typing import Any

from briefing import dart, dart_mcp, flags, mcpc
from briefing.models import Anomaly, Briefing, Disclosure, Flow, Insider, SignalRow

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


def briefing_for(
    signal: SignalRow,
    corp_code: str,
    bgn: date,
    end: date,
    *,
    flow: Flow | None = None,
    flow_skipped: bool = False,
) -> Briefing:
    """종목 하나의 브리핑 — 공시(폴백 포함) → 판정 → 보조 신호 → 시세 참고. `fetch_one`이 부른다.

    시세(`flow`)는 `load_market`이 배치 1회로 받아 둔 것을 받기만 한다 (F12).
    `flow_skipped`면 시세 층 전체가 생략된 것 — `skipped`에 `flow`를 더한다.

    Raises:
        dart.DartError: 공시를 어느 경로로도 못 받았을 때. 보조 신호는 그 전에 부르지 않는다.
    """
    raw, source = disclosures_with_fallback(corp_code, bgn, end)
    anomaly, insider, skipped = side_signals(corp_code, bgn, end)
    if flow_skipped:
        skipped = (*skipped, "flow")
    v = flags.classify(raw, company_name=signal.name, insider=insider)
    return Briefing.from_signal(
        signal,
        corp_code,
        v.level,
        flags=v.flags,
        disclosures=v.disclosures,
        anomaly=anomaly,
        insider=insider,
        flow=flow,
        source=source,
        skipped=skipped,
    )


def run_detail(briefings: Iterable[Briefing]) -> dict[str, Any]:
    """`ksb_runs.detail`용 집계 — 출처별 건수 · 생략 횟수 · anomaly verdict 분포. 순수 함수."""
    source: collections.Counter[str] = collections.Counter()
    skipped: collections.Counter[str] = collections.Counter()
    verdicts: collections.Counter[str] = collections.Counter()
    for b in briefings:
        source[b.source if b.corp_code is not None and b.level != "error" else "none"] += 1
        skipped.update(b.skipped)
        if b.anomaly is not None:
            verdicts[b.anomaly.verdict] += 1
    return {"source": dict(source), "skipped": dict(skipped), "anomaly_verdicts": dict(verdicts)}
