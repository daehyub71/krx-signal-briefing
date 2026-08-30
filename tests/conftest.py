"""그래프 테스트용 I/O 차단막.

`wiring()`은 부수효과가 있는 노드(DB·HTTP·LLM·SMTP·sleep)를 **항상 스텁으로 덮는다.**
그래프 테스트가 실DB에 붙어 깨진 사례가 상위 프로젝트에 있다 (TASKS M1 ④).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from briefing import nodes
from briefing.models import Briefing, SendResult, SignalRow
from briefing.state import GATE_READY, BriefingState, FetchItem

RUN_DATE = date(2026, 8, 25)

Node = Callable[..., dict[str, Any]]


def a_signal(ticker: str, strategy: str = "mtf", name: str = "") -> SignalRow:
    """테스트용 신호 행."""
    return SignalRow(d=RUN_DATE, strategy=strategy, ticker=ticker, name=name or ticker)


def a_briefing(item: FetchItem, level: str = "none") -> Briefing:
    """fan-out 항목 하나로 브리핑을 만든다 (DART 없이)."""
    s = item["signal"]
    return Briefing(
        d=s.d,
        strategy=s.strategy,
        ticker=s.ticker,
        name=s.name,
        corp_code=item["corp_code"],
        level=level,  # type: ignore[arg-type]
    )


def const(patch: dict[str, Any]) -> Node:
    """상태에 고정값을 쓰는 스텁 노드."""

    def node(state: BriefingState) -> dict[str, Any]:
        return dict(patch)

    return node


def trace(name: str, log: list[str], patch: dict[str, Any] | None = None) -> Node:
    """호출되면 이름을 기록하고, 주어진 값을 상태에 쓰는 스텁 노드."""

    def node(state: BriefingState) -> dict[str, Any]:
        log.append(name)
        return dict(patch or {})

    return node


def trace_then(name: str, log: list[str], fn: Node) -> Node:
    """이름을 기록한 뒤 실제 노드에 위임한다 — 부수효과가 없는 노드에만 쓴다."""

    def node(state: BriefingState) -> dict[str, Any]:
        log.append(name)
        return fn(state)

    return node


def stub_wait(log: list[str]) -> Node:
    """자지 않고 attempts만 올리는 wait. 실제 노드는 60초 잔다."""

    def node(state: BriefingState) -> dict[str, Any]:
        log.append("wait")
        return {"attempts": state.get("attempts", 0) + 1}

    return node


def stub_fetch_one(log: list[str] | None = None) -> Node:
    """DART 없이 fan-out 항목마다 브리핑 하나를 돌려주는 스텁."""

    def node(item: FetchItem) -> dict[str, Any]:
        if log is not None:
            log.append(f"fetch_one:{item['signal'].ticker}")
        return {"briefings": [a_briefing(item)], "dart_calls": 1}

    return node


def wiring(log: list[str] | None = None, **custom: Node) -> dict[str, Node]:
    """I/O 노드를 전부 스텁으로 덮은 overrides. `custom`으로 개별 노드를 갈아끼운다.

    Args:
        log: 주면 도달한 노드 이름을 순서대로 기록한다.
        **custom: 노드 이름 → 대체 함수.

    Returns:
        `build_graph(overrides=...)`에 넘길 사전.
    """
    log = log if log is not None else []
    base: dict[str, Node] = {
        "gate": trace("gate", log, {"gate": GATE_READY, "data_date": RUN_DATE}),
        "wait": stub_wait(log),  # 실제 노드는 60초 잔다 — 테스트에서는 절대 부르지 않는다
        "load_signals": trace("load_signals", log, {"signals": [], "existing": {}}),
        "load_corps": trace("load_corps", log, {"corp_codes": {}}),
        "load_market": trace("load_market", log, {"flows": {}, "flow_skipped": ""}),
        "fetch_one": stub_fetch_one(log),
        "analyze": trace("analyze", log, {"summaries": {}, "verdicts": {}}),
        "render": trace("render", log, {"subject": "s", "text": "t", "html": "h"}),
        "persist": trace("persist", log),
        "send_email": trace("send_email", log, {"send": SendResult(ok=True, sent_n=1)}),
        # 상태 판정(_status_of)은 record_run 안에 있다 — 스텁이 이걸 건너뛰면
        # send_failed·gate_timeout이 절대 안 나온다. dry_run이라 DB는 타지 않는다.
        "record_run": trace_then("record_run", log, nodes.record_run),
    }
    base.update(custom)
    return base
