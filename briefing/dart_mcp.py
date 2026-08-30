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
from briefing.models import Anomaly, Disclosure, EventBody, Insider

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

# ── 공시 본문 (SPEC F15, v3.0) ───────────────────────────────────
#
# `report_nm` 한 줄로는 무슨 일인지 알 수 없다. 규칙이 걸린 공시에 한해 본문을 읽는다.
# **정형 공시(F16)의 본문은 부르지 않는다** — 호출이 폭증하고 읽을 것도 없다.

# 규칙 id → `get_corporate_event`의 `event_type`.
# 대응이 없는 규칙은 여기 넣지 않는다 — 없는 값을 지어내면 서버가 400을 준다.
# `tests/test_event_body.py`가 규칙표에 실재하는 id인지 확인한다.
EVENT_TYPE_OF: dict[str, str] = {
    "cb": "cb_issuance",
    "bw": "bw_issuance",
    "eb": "eb_issuance",
    "rights_issue": "rights_offering",
    "capital_reduction": "capital_reduction",
    "lawsuit": "litigation",
    "rehabilitation": "rehabilitation_filing",
    "treasury_sale": "treasury_disposal",
}

# 자금 용도 칸 — DART 필드명과 사람이 읽는 이름.
USE_OF_FUNDS: tuple[tuple[str, str], ...] = (
    ("fdpp_fclt", "시설자금"),
    ("fdpp_bsninh", "영업양수자금"),
    ("fdpp_op", "운영자금"),
    ("fdpp_dtrp", "채무상환자금"),
    ("fdpp_ocsa", "타법인증권취득자금"),
    ("fdpp_etc", "기타자금"),
)

# DART가 빈 값에 쓰는 표기. 0원과 다르다.
ABSENT = ("-", "", "해당사항없음", "미해당")


def _num(raw: Any) -> str:
    return str(raw).strip().replace(",", "") if raw is not None else ""


def _int_or_none(raw: Any) -> int | None:
    """쉼표 낀 숫자 → int. `-`나 읽을 수 없는 값이면 None (그 칸만 비운다)."""
    if raw is None or str(raw).strip() in ABSENT:
        return None
    try:
        return int(float(_num(raw)))
    except (TypeError, ValueError):
        return None


def _float_or_none(raw: Any) -> float | None:
    if raw is None or str(raw).strip() in ABSENT:
        return None
    try:
        return float(_num(raw))
    except (TypeError, ValueError):
        return None


def _text(raw: Any) -> str:
    v = str(raw).strip() if raw is not None else ""
    return "" if v in ABSENT else v


def parse_events(payload: dict[str, Any], event_type: str) -> tuple[EventBody, ...]:
    """`get_corporate_event` 응답 → `EventBody` 목록. **순수 함수.**

    Args:
        payload: MCP 응답을 JSON으로 읽은 것.
        event_type: 요청했던 `event_type` (응답에 없을 수 있어 받아 둔다).

    Returns:
        본문 목록. 빈 응답·실패 상태면 빈 튜플 — 여기서 예외를 내지 않는다.
        본문은 **있으면 좋은 층**이라 없으면 제목만 쓴다.
    """
    status = str(payload.get("status", "000"))
    if status not in ("000", ""):
        return ()
    items = payload.get("items") or ()
    out: list[EventBody] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        funds = tuple(
            (label, amount)
            for key, label in USE_OF_FUNDS
            if (amount := _int_or_none(it.get(key))) is not None
        )
        out.append(
            EventBody(
                rcept_no=str(it.get("rcept_no", "")),
                event_type=event_type,
                decided_on=_text(it.get("bddd")),
                amount=_int_or_none(it.get("bd_fta")),
                use_of_funds=funds,
                kind=_text(it.get("bd_knd")),
                method=_text(it.get("bdis_mthn")),
                coupon_rate=_float_or_none(it.get("bd_intr_ex")),
                ytm_rate=_float_or_none(it.get("bd_intr_sf")),
                maturity=_text(it.get("bd_mtd")),
                conv_price=_int_or_none(it.get("cv_prc")),
                conv_shares=_int_or_none(it.get("cvisstk_cnt")),
                overhang_pct=_float_or_none(it.get("cvisstk_tisstk_vs")),
                conv_from=_text(it.get("cvrqpd_bgd")),
                conv_to=_text(it.get("cvrqpd_edd")),
                outstanding=_int_or_none(it.get("atcsc_rmislmt")),
                refix_floor=_int_or_none(it.get("act_mktprcfl_cvprc_lwtrsprc")),
            )
        )
    return tuple(out)


def fetch_event(
    corp_code: str, rule: str, bgn: date, end: date, *, server: Any = None
) -> tuple[EventBody, ...]:
    """규칙 하나에 해당하는 공시 본문을 읽는다 (F15).

    **인자 이름은 `start`·`end`다** — `bgn_de`/`end_de`로 부르면 `status: 100`
    (필수값 누락)이 돌아온다. 2026-08-30에 그렇게 한 번 헛돌았다.

    Args:
        corp_code: DART 고유번호 8자리.
        rule: `flags.RULES`의 id. 매핑이 없으면 부르지 않는다.
        bgn: 조회 시작일.
        end: 조회 종료일.
        server: MCP 세션 (테스트가 대역을 넣는다).

    Returns:
        본문 목록. 매핑이 없거나 결과가 없으면 빈 튜플.

    Raises:
        mcpc.McpError: 호출 실패. 호출자가 생략으로 삼킨다 (D15).
    """
    event_type = EVENT_TYPE_OF.get(rule)
    if event_type is None:
        return ()
    srv = server or mcpc.get("dart")
    payload = srv.call_json(
        "get_corporate_event",
        {
            "corp": corp_code,
            "event_type": event_type,
            "start": bgn.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
        },
        timeout=TIMEOUT,
    )
    return parse_events(payload, event_type)

