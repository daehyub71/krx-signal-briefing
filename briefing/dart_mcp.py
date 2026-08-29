"""korean-dart-mcp 도구 호출 → 도메인 모델 (F4·F4b, SPEC D13).

세 도구를 쓴다. 호출은 `mcpc.get("dart")` 세션으로, 실패는 `mcpc.McpError`로 그대로 올린다 —
공시(F4)는 호출자가 REST(`dart.py`)로 폴백하고, anomaly·insider(F4b)는 생략한다 (D15).

**응답 → 모델 변환은 여기 순수 함수(`parse_*`)에 있다.** 계약 테스트는 실제 응답 표본
(`tests/fixtures/mcp_*.json`)으로 한다. 서버 버전을 올릴 때 이 표본을 다시 뽑아 돌린다 (N14).

`search_disclosures` 인자는 REST `list.json`과 **같은 목록**을 주는 조합으로 고정한다
(2026-08-29 실측: `all_pages`만 주면 정정공시가 빠지고(53건),
`include_corrections`까지 줘야 61 = 61).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Protocol

from briefing import mcpc
from briefing.models import Anomaly, Disclosure, Insider

TIMEOUT = 30.0
LIMIT = 200  # 30일 창에서 200건을 넘는 종목은 없다고 본다 (REST는 100 — 실측 최대 61)


class _Server(Protocol):
    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = ...
    ) -> Any: ...


def _dart() -> _Server:
    return mcpc.get("dart")


# ── 공시 (F4) ────────────────────────────────────────────────────


def disclosure_args(corp_code: str, bgn: date, end: date) -> dict[str, Any]:
    """`search_disclosures` 인자 — REST와 같은 목록을 주는 조합으로 고정."""
    return {
        "corp": corp_code,
        "begin": bgn.isoformat(),
        "end": end.isoformat(),
        "all_pages": True,
        "include_corrections": True,
        "limit": LIMIT,
    }


def parse_disclosures(payload: dict[str, Any]) -> list[Disclosure]:
    """`search_disclosures` 응답(page/batch 모드 공통) → Disclosure 목록. 순서는 응답 그대로."""
    return [Disclosure.from_dart_item(x) for x in payload.get("items") or []]


def fetch_disclosures(
    corp_code: str, bgn: date, end: date, *, server: _Server | None = None
) -> list[Disclosure]:
    """한 회사의 기간 내 공시 목록 — MCP 경로.

    실패는 `mcpc.McpError`로 올린다 — 호출자가 REST로 폴백한다 (D15).
    """
    srv = server or _dart()
    return parse_disclosures(
        srv.call_json("search_disclosures", disclosure_args(corp_code, bgn, end), timeout=TIMEOUT)
    )


# ── 보조 신호 (F4b) ──────────────────────────────────────────────


def parse_anomaly(payload: dict[str, Any]) -> Anomaly:
    """`disclosure_anomaly` 응답 → Anomaly. `score`·`verdict`가 없으면 ValueError."""
    if "score" not in payload or "verdict" not in payload:
        raise ValueError(f"disclosure_anomaly 응답에 score/verdict가 없다: {list(payload)[:6]}")
    flags = tuple(
        f if isinstance(f, str) else json.dumps(f, ensure_ascii=False)
        for f in payload.get("flags") or []
    )
    return Anomaly(
        score=int(payload["score"]),
        verdict=str(payload["verdict"]),
        summary=str(payload.get("summary_text") or "").strip(),
        flags=flags,
    )


def fetch_anomaly(corp_code: str, *, server: _Server | None = None) -> Anomaly:
    """공시 이상 점수 (3년 창은 서버 기본값). 보조 신호 — 등급을 바꾸지 않는다."""
    srv = server or _dart()
    return parse_anomaly(srv.call_json("disclosure_anomaly", {"corp": corp_code}, timeout=TIMEOUT))


def parse_insider(payload: dict[str, Any]) -> Insider:
    """`insider_signal` 응답 → Insider. `summary`가 없으면 신호 없음."""
    s = payload.get("summary") or {}
    return Insider(
        signal=str(s.get("signal") or "none"),
        buy_events=int(s.get("buy_events") or 0),
        sell_events=int(s.get("sell_events") or 0),
        unique_buyers=int(s.get("unique_buyers") or 0),
        unique_sellers=int(s.get("unique_sellers") or 0),
        net_change_shares=int(s.get("net_change_shares") or 0),
        summary=str(payload.get("summary_text") or "").strip(),
    )


def fetch_insider(
    corp_code: str, bgn: date, end: date, *, server: _Server | None = None
) -> Insider:
    """임원·주요주주 매매 군집 — 같은 30일 창."""
    srv = server or _dart()
    args = {"corp": corp_code, "start": bgn.isoformat(), "end": end.isoformat()}
    return parse_insider(srv.call_json("insider_signal", args, timeout=TIMEOUT))
