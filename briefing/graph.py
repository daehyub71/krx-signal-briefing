"""LangGraph 상태 그래프 조립.

구조는 `docs/PLAN.md` §1-1, 설계도는 `docs/graph.png`, 실제 그래프는 `docs/GRAPH.md`를 본다.
이 모듈은 배선만 한다 — 판정 로직은 노드 밖 도메인 모듈에 있다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from briefing import nodes
from briefing.state import RECURSION_LIMIT, BriefingState

# 네트워크를 타면서 예외를 내는 노드에만 재시도를 건다.
# fetch_one·summarize·send_email은 예외를 밖으로 내지 않으므로 노드 재시도가 걸리지 않는다 —
# 전송 재시도는 각 클라이언트 안에서 한다 (PLAN §1-1).
NETWORK_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0)


def build_graph(overrides: Mapping[str, Callable[..., Any]] | None = None) -> Any:
    """그래프를 만들어 컴파일한다.

    Args:
        overrides: 노드 이름 → 대체 함수. 테스트가 I/O 노드를 스텁으로 갈아끼워
            **배선만** 검사할 때 쓴다. 운영에서는 넘기지 않는다.

    Returns:
        컴파일된 그래프 (`recursion_limit` 적용).
    """
    sub = dict(overrides or {})

    def pick(name: str, fn: Callable[..., Any]) -> Any:
        # 반환형이 Any인 것은 의도적이다. LangGraph의 add_node 오버로드가
        # 평범한 Callable을 받아들이지 못해 strict 모드에서 걸린다 — 프레임워크
        # 경계에서만 완화하고, 우리 쪽 타입은 overrides 시그니처가 지킨다.
        return sub.get(name, fn)

    g: StateGraph[BriefingState, Any, Any, Any] = StateGraph(BriefingState)

    g.add_node("gate", pick("gate", nodes.gate), retry_policy=NETWORK_RETRY)
    g.add_node("wait", pick("wait", nodes.wait))
    g.add_node("load_signals", pick("load_signals", nodes.load_signals), retry_policy=NETWORK_RETRY)
    g.add_node("load_corps", pick("load_corps", nodes.load_corps), retry_policy=NETWORK_RETRY)
    g.add_node("fetch_one", pick("fetch_one", nodes.fetch_one))
    g.add_node("summarize", pick("summarize", nodes.summarize))
    g.add_node("render", pick("render", nodes.render))
    g.add_node("persist", pick("persist", nodes.persist))
    g.add_node("send_email", pick("send_email", nodes.send_email))
    g.add_node("record_run", pick("record_run", nodes.record_run))
    g.add_node("finalize", pick("finalize", nodes.finalize))

    g.add_edge(START, "gate")

    # 게이트 — 판정이 그래프 위에 드러나 있다 (F1). missing이면 wait를 거쳐 gate로 돌아온다(사이클).
    # timeout은 finalize 직행이 아니라 record_run으로 — 실패해도 기록이 먼저다.
    g.add_conditional_edges(
        "gate",
        pick("route_gate", nodes.route_gate),
        {
            "ready": "load_signals",
            "stale": "render",
            "missing": "wait",
            "timeout": "record_run",
        },
    )
    g.add_edge("wait", "gate")

    g.add_edge("load_signals", "load_corps")

    # 종목별 fan-out → summarize에서 합류. briefings 리듀서가 결과를 합친다.
    # 신호 0건이면 Send 없이 summarize로 직행한다 — 빈 Send 목록은 그래프를 조용히 끝낸다.
    g.add_conditional_edges(
        "load_corps", pick("fan_out", nodes.fan_out), ["fetch_one", "summarize"]
    )
    g.add_edge("fetch_one", "summarize")

    g.add_edge("summarize", "render")
    g.add_edge("render", "persist")
    g.add_edge("persist", "send_email")
    g.add_edge("send_email", "record_run")
    g.add_edge("record_run", "finalize")
    g.add_edge("finalize", END)

    return g.compile().with_config(recursion_limit=RECURSION_LIMIT)
