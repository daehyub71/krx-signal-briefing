"""그래프 배선 테스트.

**여기서 검사하는 것은 배관이지 도메인 로직이 아니다** (SPEC N11).
판정·렌더·검증은 각 순수 함수 테스트가 직접 부른다.

이 파일이 지키는 네 가지 (TASKS M0):
  ① 게이트 ready / stale / missing 세 경로가 실제로 갈라진다
  ② missing이 10회를 넘으면 record_run → finalize(gate_timeout)로 끝난다
     — 무한 루프도, 조용한 성공도 아니다
  ③ Send fan-out N개의 결과가 **전부** 합쳐진다 — 리듀서 누락은 예외 없이 조용히 틀린다
  ④ summarize·send_email이 실패해도 record_run에 도달한다 — 안 그러면 실패 기록이 사라진다
"""

from __future__ import annotations

from typing import Any

import pytest

from briefing.graph import build_graph
from briefing.models import SendResult
from briefing.nodes import BriefingRunError
from briefing.state import (
    GATE_MISSING,
    GATE_STALE,
    STATUS_GATE_TIMEOUT,
    STATUS_NO_SIGNALS,
    STATUS_OK,
    STATUS_SEND_FAILED,
    initial_state,
)
from tests.conftest import RUN_DATE, a_signal, trace, wiring


def run(overrides: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """스텁 배선으로 그래프를 끝까지 돌린다."""
    state = initial_state(RUN_DATE, dry_run=True, **kw)
    result: dict[str, Any] = build_graph(overrides).invoke(state)
    return result


# ── ① 게이트 세 경로 ────────────────────────────────────────────


def test_gate_ready_goes_through_full_path() -> None:
    log: list[str] = []
    out = run(wiring(log))
    assert log == [
        "gate", "load_signals", "load_corps", "summarize", "render",
        "persist", "send_email", "record_run",
    ]
    assert out["status"] == STATUS_NO_SIGNALS  # 신호 0건 — "브리핑 없음"도 발송한다 (D8)


def test_gate_stale_skips_to_render() -> None:
    """데이터 지연이면 신호 없이 [브리핑 없음] 메일로 합류한다 (D8)."""
    log: list[str] = []
    run(wiring(log, gate=trace("gate", log, {"gate": GATE_STALE, "data_date": RUN_DATE})))
    assert "load_signals" not in log and "load_corps" not in log
    assert log[-4:] == ["render", "persist", "send_email", "record_run"]


def test_gate_missing_waits_then_retries() -> None:
    """행이 없으면 wait를 거쳐 gate로 돌아온다 (사이클)."""
    log: list[str] = []
    calls = {"n": 0}

    def gate(state: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        log.append("gate")
        if calls["n"] < 3:
            return {"gate": GATE_MISSING}
        return {"gate": "ready", "data_date": RUN_DATE}

    run(wiring(log, gate=gate))
    assert log[:5] == ["gate", "wait", "gate", "wait", "gate"]
    assert "load_signals" in log


# ── ② 루프 상한 ────────────────────────────────────────────────


def test_gate_missing_ten_times_fails_loudly_after_recording() -> None:
    log: list[str] = []
    always_missing = trace("gate", log, {"gate": GATE_MISSING})
    with pytest.raises(BriefingRunError, match=STATUS_GATE_TIMEOUT):
        run(wiring(log, gate=always_missing))
    # 확인 11회 · 대기 10회 — 마지막 대기 뒤에 한 번 더 확인해야 60초가 헛되지 않다
    assert log.count("gate") == 11 and log.count("wait") == 10
    assert log[-1] == "record_run"  # 실패해도 기록이 먼저다
    assert "load_signals" not in log


# ── ③ fan-out 합류 ─────────────────────────────────────────────


def test_fan_out_collects_every_briefing() -> None:
    """리듀서가 빠지면 마지막 하나만 남고 예외도 안 난다. 이 테스트가 유일한 방어선이다."""
    log: list[str] = []
    signals = [a_signal("000001"), a_signal("000002", "vcp"), a_signal("000003")]
    out = run(
        wiring(
            log,
            load_signals=trace("load_signals", log, {"signals": signals, "existing": {}}),
            load_corps=trace("load_corps", log, {"corp_codes": {"000001": "00000001"}}),
        )
    )
    assert sorted(b.ticker for b in out["briefings"]) == ["000001", "000002", "000003"]
    assert out["dart_calls"] == 3
    assert log.count("load_corps") == 1 and log.count("summarize") == 1
    fetched = [x for x in log if x.startswith("fetch_one:")]
    assert len(fetched) == 3
    # corp_code는 항목별로 실려 간다 — 없는 종목은 None
    by_ticker = {b.ticker: b.corp_code for b in out["briefings"]}
    assert by_ticker == {"000001": "00000001", "000002": None, "000003": None}


def test_fan_out_with_zero_signals_still_reaches_summarize() -> None:
    """조건부 엣지가 빈 목록을 돌려주면 그래프가 거기서 조용히 끝난다 — 그러면 안 된다."""
    log: list[str] = []
    out = run(wiring(log))
    assert not [x for x in log if x.startswith("fetch_one:")]
    assert "summarize" in log and "record_run" in log
    assert out["briefings"] == []


# ── ④ 실패해도 record_run 도달 ─────────────────────────────────


def test_summarize_failure_does_not_block_mail() -> None:
    """LLM은 있으면 좋은 층이다 (R11) — 실패해도 status는 ok."""
    log: list[str] = []
    signals = [a_signal("000001")]
    out = run(
        wiring(
            log,
            load_signals=trace("load_signals", log, {"signals": signals, "existing": {}}),
            summarize=trace("summarize", log, {"summary_error": "APIConnectionError"}),
        )
    )
    assert log[-3:] == ["persist", "send_email", "record_run"]
    assert out["status"] == STATUS_OK and out["summary_error"] == "APIConnectionError"


def test_send_failure_reaches_record_run_then_raises() -> None:
    log: list[str] = []
    result = SendResult(ok=False, error="SMTPAuthenticationError")
    failed = trace("send_email", log, {"send": result})
    with pytest.raises(BriefingRunError, match=STATUS_SEND_FAILED):
        run(wiring(log, send_email=failed))
    assert log[-2:] == ["send_email", "record_run"]
