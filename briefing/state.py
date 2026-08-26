"""그래프 상태 정의.

**여러 노드가 동시에 쓰는 키에는 반드시 리듀서가 붙어야 한다.**
리듀서가 없으면 LangGraph는 마지막에 도착한 값으로 조용히 덮어쓴다 — 예외도 나지 않는다.
`briefings`·`dart_calls`는 종목별 `Send` fan-out 노드 N개가 동시에 쓴다.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, TypedDict

from briefing.models import Briefing, SendResult, SignalRow

# ── 게이트 판정값 (F1) ─────────────────────────────────────────
GATE_READY = "ready"      # 오늘 ksa_runs 행 있음 · 신호 저장됨
GATE_STALE = "stale"      # 상위가 데이터 지연으로 신호를 만들지 않음 → [브리핑 없음] (D8)
GATE_MISSING = "missing"  # 행 없음 → wait 후 재시도

# 1분 × 10회. dispatch 경로에서는 보통 첫 시도에 있다 — 10분을 기다리는 것은
# 상위가 record_run 전에 죽은 경우를 잡기 위해서다 (SPEC F1).
MAX_GATE_ATTEMPTS = 10
GATE_WAIT_SECONDS = 60

# 게이트 루프(gate+wait) 최대 22스텝 + 뒤 노드 8개. 기본값 25로는 모자란다.
RECURSION_LIMIT = 40

# ── ksb_runs.status (models.RunStatus와 같은 문자열) ────────────
STATUS_OK = "ok"
STATUS_NO_SIGNALS = "no_signals"
STATUS_GATE_TIMEOUT = "gate_timeout"
STATUS_DART_PARTIAL = "dart_partial"
STATUS_DART_FAILED = "dart_failed"
STATUS_SEND_FAILED = "send_failed"

# finalize가 예외를 올리는 상태 (SPEC N5)
FAILING_STATUSES = (
    STATUS_GATE_TIMEOUT, STATUS_DART_PARTIAL, STATUS_DART_FAILED, STATUS_SEND_FAILED
)


def briefing_key(strategy: str, ticker: str) -> str:
    """`existing`·`summaries` 사전의 키. `(d, strategy, ticker)` 중 d는 상태에 하나뿐이다."""
    return f"{strategy}:{ticker}"


class FetchItem(TypedDict):
    """`Send("fetch_one", …)`로 넘기는 종목 하나의 입력. fan-out 노드는 전체 상태를 받지 않는다."""

    signal: SignalRow
    corp_code: str | None
    existing: Briefing | None
    force: bool


class BriefingState(TypedDict, total=False):
    """그래프를 흐르는 상태.

    `total=False`인 것은 노드가 자기가 바꾼 키만 반환하기 때문이다.
    초기 상태는 `initial_state()`로 만든다.
    """

    # 입력 — main이 주입한다. 노드는 "오늘"을 직접 알지 못한다.
    run_date: date
    dry_run: bool
    force: bool

    # 게이트 (F1)
    gate: str
    attempts: int
    data_date: date | None

    # 입력 적재 (F2·F3)
    signals: list[SignalRow]
    existing: dict[str, Briefing]   # briefing_key → 그날 이미 있는 브리핑 (멱등)
    corp_codes: dict[str, str]      # ticker → corp_code

    # fan-out 합류 — 리듀서 필수
    briefings: Annotated[list[Briefing], operator.add]
    dart_calls: Annotated[int, operator.add]

    # 요약 (F14)
    summaries: dict[str, str]       # briefing_key → summary
    summary_error: str
    llm_tokens: int

    # 출력
    subject: str
    text: str
    html: str
    send: SendResult | None
    status: str


def initial_state(run_date: date, *, dry_run: bool = False, force: bool = False) -> BriefingState:
    """그래프에 넣을 초기 상태를 만든다.

    Args:
        run_date: 실행 기준일. 재현은 과거 날짜를 넣는다.
        dry_run: True면 저장·발송하지 않는다.
        force: True면 기존 브리핑·요약이 있어도 다시 만든다 (DART·LLM 재호출).

    Returns:
        모든 키가 채워진 초기 상태.
    """
    return BriefingState(
        run_date=run_date,
        dry_run=dry_run,
        force=force,
        gate=GATE_MISSING,
        attempts=0,
        data_date=None,
        signals=[],
        existing={},
        corp_codes={},
        briefings=[],
        dart_calls=0,
        summaries={},
        summary_error="",
        llm_tokens=0,
        subject="",
        text="",
        html="",
        send=None,
        status=STATUS_OK,
    )
