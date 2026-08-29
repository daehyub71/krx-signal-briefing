"""dart_mcp — korean-dart-mcp 응답 → 도메인 모델. 계약 테스트는 실제 응답 표본으로.

지키는 것:
  · MCP 경로와 REST 경로(dart.py)는 **같은 매핑**(`Disclosure.from_dart_item`)을 쓴다
  · 호출 인자는 REST와 같은 목록을 주는 조합으로 고정한다
    (실측: all_pages + include_corrections → 61 = 61)
  · anomaly·insider는 보조 신호다 — 파싱 실패도 예외로 드러낸다 (호출자가 생략 처리)
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from briefing import dart, dart_mcp
from briefing.dart_mcp import (
    disclosure_args,
    fetch_anomaly,
    fetch_disclosures,
    fetch_insider,
    parse_anomaly,
    parse_disclosures,
    parse_insider,
)
from briefing.mcpc import McpCallError
from briefing.models import Anomaly, Disclosure, Insider

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "mcp_search_disclosures.json").read_text(encoding="utf-8"))
ANOMALY = json.loads((FIXTURES / "mcp_anomaly.json").read_text(encoding="utf-8"))
INSIDER = json.loads((FIXTURES / "mcp_insider.json").read_text(encoding="utf-8"))

CORP, END = "00126380", date(2026, 8, 29)
BGN = END - timedelta(days=30)


class FakeServer:
    """mcpc.McpServer 대역 — call_json만 흉내 낸다."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = 30.0
    ) -> Any:
        self.calls.append((tool, dict(args or {}), timeout))
        reply = self.replies[tool]
        if isinstance(reply, Exception):
            raise reply
        return reply


# ── 공시 (F4) ────────────────────────────────────────────────────


def test_parse_disclosures_maps_items_in_order() -> None:
    out = parse_disclosures(SEARCH)
    assert len(out) == 20 and len(SEARCH["items"]) == 20
    assert out[0] == Disclosure(
        rcept_dt=date(2026, 8, 28),
        report_nm="주식등의대량보유상황보고서(일반)",
        rcept_no="20260828001916",
        flr_nm="삼성물산",
    )
    assert [d.rcept_no for d in out] == [x["rcept_no"] for x in SEARCH["items"]]
    assert all(d.corrected is False for d in out)  # 정정 표시는 flags.classify가 붙인다


def test_parse_disclosures_empty_and_missing_items() -> None:
    assert parse_disclosures({"mode": "batch", "items": []}) == []
    assert parse_disclosures({"mode": "batch"}) == []


def test_mcp_and_rest_share_the_same_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 항목을 REST 경로(dart.fetch_disclosures)로 흘려도 결과가 바이트 단위로 같다."""
    items = SEARCH["items"]
    body = json.dumps(
        {"status": "000", "message": "정상", "total_count": len(items), "list": items}
    )

    class Resp:
        def read(self) -> bytes:
            return body.encode("utf-8")

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    monkeypatch.setenv("DART_API_KEY", "x" * 40)
    monkeypatch.setattr(dart, "urlopen", lambda req, timeout=None: Resp())
    via_rest = dart.fetch_disclosures(CORP, BGN, END)
    via_mcp = parse_disclosures(SEARCH)
    assert via_rest == via_mcp


def test_disclosure_args_pin_the_rest_equivalent_combination() -> None:
    """실측(2026-08-29): all_pages만 주면 정정공시 8건이 빠진다(53).

    include_corrections까지 줘야 61 = 61.
    """
    assert disclosure_args(CORP, BGN, END) == {
        "corp": CORP,
        "begin": "2026-07-30",
        "end": "2026-08-29",
        "all_pages": True,
        "include_corrections": True,
        "limit": 200,
    }


def test_fetch_disclosures_calls_server_with_pinned_args() -> None:
    srv = FakeServer({"search_disclosures": SEARCH})
    out = fetch_disclosures(CORP, BGN, END, server=srv)
    assert len(out) == 20
    assert srv.calls == [("search_disclosures", disclosure_args(CORP, BGN, END), dart_mcp.TIMEOUT)]


def test_fetch_disclosures_propagates_mcp_errors() -> None:
    """폴백 판단은 호출자(fetch_one)의 몫 — 여기서 삼키지 않는다."""
    srv = FakeServer({"search_disclosures": McpCallError("타임아웃")})
    with pytest.raises(McpCallError):
        fetch_disclosures(CORP, BGN, END, server=srv)


# ── anomaly (F4b) ────────────────────────────────────────────────


def test_parse_anomaly() -> None:
    a = parse_anomaly(ANOMALY)
    assert a == Anomaly(score=0, verdict="clean", summary=a.summary, flags=())
    assert a.summary.startswith("삼성전자") and "점수 0/100" in a.summary


def test_parse_anomaly_with_flags_and_missing_fields() -> None:
    a = parse_anomaly({"score": "68", "verdict": "warning", "flags": ["auditor_change", {"x": 1}]})
    assert a.score == 68 and a.verdict == "warning" and a.summary == ""
    assert a.flags == ("auditor_change", '{"x": 1}')


def test_parse_anomaly_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_anomaly({"verdict": "clean"})  # score 없음


def test_fetch_anomaly_calls_server() -> None:
    srv = FakeServer({"disclosure_anomaly": ANOMALY})
    assert fetch_anomaly(CORP, server=srv).verdict == "clean"
    assert srv.calls[0][:2] == ("disclosure_anomaly", {"corp": CORP})


# ── insider (F4b) ────────────────────────────────────────────────


def test_parse_insider_reads_summary() -> None:
    i = parse_insider(INSIDER)
    assert i == Insider(
        signal="strong_sell_cluster",
        buy_events=10,
        sell_events=29,
        unique_buyers=7,
        unique_sellers=28,
        net_change_shares=-16835,
        summary=i.summary,
    )
    assert i.sell_cluster is True and "매도 클러스터" in i.summary


def test_parse_insider_without_summary_is_none_signal() -> None:
    i = parse_insider({"resolved": {}, "period": {}})
    assert i.signal == "none" and i.sell_cluster is False and i.sell_events == 0


@pytest.mark.parametrize(
    ("signal", "sell"), [("sell_cluster", True), ("buy_cluster", False), ("none", False)]
)
def test_insider_sell_cluster_property(signal: str, sell: bool) -> None:
    assert Insider(signal=signal).sell_cluster is sell


def test_fetch_insider_uses_window() -> None:
    srv = FakeServer({"insider_signal": INSIDER})
    fetch_insider(CORP, BGN, END, server=srv)
    assert srv.calls[0][:2] == (
        "insider_signal",
        {"corp": CORP, "start": "2026-07-30", "end": "2026-08-29"},
    )


# ── 실서버 통합 — MCP_INTEGRATION=1일 때만 (Node · DART 키 · 네트워크) ─────


@pytest.mark.skipif(os.environ.get("MCP_INTEGRATION") != "1", reason="MCP_INTEGRATION=1일 때만")
def test_live_mcp_matches_rest_for_same_corp_and_window() -> None:
    """M1b 완료 기준: 같은 종목·같은 창에서 MCP와 REST의 공시 목록이 일치한다."""
    from briefing import config, mcpc

    config.load_env()
    end = date.today()
    bgn = end - timedelta(days=30)
    try:
        via_mcp = fetch_disclosures(CORP, bgn, end)
        via_rest = dart.fetch_disclosures(CORP, bgn, end)
    finally:
        mcpc.close_all()
    assert {d.rcept_no for d in via_mcp} == {d.rcept_no for d in via_rest}
    assert sorted(via_mcp, key=lambda d: d.rcept_no) == sorted(via_rest, key=lambda d: d.rcept_no)
