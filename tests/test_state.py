"""state — 리듀서가 붙어 있는지. 빠지면 fan-out 결과가 조용히 덮인다."""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, get_args, get_origin, get_type_hints

from briefing.state import (
    GATE_MISSING,
    MAX_GATE_ATTEMPTS,
    RECURSION_LIMIT,
    BriefingState,
    briefing_key,
    initial_state,
)


def reducer_of(key: str) -> object:
    """상태 키에 붙은 리듀서 함수를 꺼낸다. 없으면 None."""
    hint = get_type_hints(BriefingState, include_extras=True)[key]
    if get_origin(hint) is not Annotated:
        return None
    return get_args(hint)[1]


def test_briefings_has_add_reducer() -> None:
    """Send fan-out N개가 전부 합쳐져야 한다 (PLAN §1-1)."""
    assert reducer_of("briefings") is operator.add


def test_dart_calls_has_add_reducer() -> None:
    assert reducer_of("dart_calls") is operator.add


def test_single_writer_keys_have_no_reducer() -> None:
    """한 노드만 쓰는 키에 리듀서를 붙이면 재실행 시 값이 누적된다."""
    for key in ("signals", "corp_codes", "summaries", "subject", "status"):
        assert reducer_of(key) is None, key


def test_initial_state_fills_every_key() -> None:
    """`total=False`라도 초기 상태는 전부 채운다 — 노드가 `state["x"]`로 안심하고 읽게."""
    s = initial_state(date(2026, 8, 25), dry_run=True, force=False)
    assert set(s) == set(get_type_hints(BriefingState))
    assert s["gate"] == GATE_MISSING and s["attempts"] == 0
    assert s["briefings"] == [] and s["dart_calls"] == 0
    assert s["dry_run"] is True and s["force"] is False


def test_recursion_limit_covers_gate_loop() -> None:
    """게이트 10회 루프(gate+wait = 20스텝) + 뒤 노드 8개가 들어가야 한다."""
    assert RECURSION_LIMIT >= MAX_GATE_ATTEMPTS * 2 + 10


def test_briefing_key_is_strategy_and_ticker() -> None:
    assert briefing_key("mtf", "079940") == "mtf:079940"
