"""공시 본문 파싱 (SPEC F15, v3.0).

`report_nm` 한 줄로는 무슨 일인지 알 수 없다. 표본은 **2026-08-26 실응답**이다
(`tests/fixtures/mcp_corporate_event.json`) — 씨피시스템 CB 1건, 엔투텍 CB 2건.

같은 `주요사항보고서(전환사채권발행결정)`인데 오버행이 5.10%와 18.63%다.
그 차이를 읽어 내는 것이 이 파서의 존재 이유다.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from briefing import dart_mcp

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "mcp_corporate_event.json").read_text(
        encoding="utf-8"
    )
)
CPS = FIXTURE["cb_issuance"][0]  # 씨피시스템
N2 = FIXTURE["cb_issuance"][1]  # 엔투텍


# ── 실응답 파싱 ──────────────────────────────────────────────────


def test_parses_the_convertible_bond_that_started_all_this() -> None:
    """씨피시스템 08/26 — 제목 한 줄이 이만큼으로 펴진다."""
    (body,) = dart_mcp.parse_events(CPS, "cb_issuance")
    assert body.rcept_no == "20260826000286"
    assert body.event_type == "cb_issuance"
    assert body.amount == 10_000_000_000
    assert body.use_of_funds == (("시설자금", 10_000_000_000),)
    assert body.method == "사모"
    assert body.coupon_rate == 0.0 and body.ytm_rate == 0.0
    assert body.conv_price == 5_106
    assert body.conv_shares == 1_958_480
    assert body.overhang_pct == 5.10
    assert body.outstanding == 23_420_000_000
    assert body.conv_from.startswith("2027") and body.conv_to.startswith("2031")


def test_parses_a_second_company_with_a_very_different_shape() -> None:
    """같은 제목·같은 event_type인데 숫자가 전혀 다르다 — 그것이 요점이다."""
    bodies = dart_mcp.parse_events(N2, "cb_issuance")
    assert len(bodies) == 2
    first = bodies[0]
    assert first.amount == 12_000_000_000
    assert first.use_of_funds == (("타법인증권취득자금", 12_000_000_000),)
    assert first.coupon_rate == 4.0 and first.ytm_rate == 4.0
    assert first.overhang_pct == 18.63  # 씨피시스템은 5.10
    assert first.outstanding == 4_891_000_000_820
    assert first.refix_floor == 1_064  # 시가하락 시 전환가 하한


def test_every_parsed_body_keeps_its_receipt_number() -> None:
    """본문을 공시에 붙이려면 접수번호가 열쇠다."""
    for payload in (CPS, N2):
        for body in dart_mcp.parse_events(payload, "cb_issuance"):
            assert body.rcept_no.isdigit() and len(body.rcept_no) == 14


# ── 값 정리 ──────────────────────────────────────────────────────


def test_a_dash_means_absent_not_zero() -> None:
    """DART는 빈 값을 `-`로 준다. 0원과 다르다."""
    payload = {"items": [{"rcept_no": "1", "bd_fta": "-", "cv_prc": "-", "fdpp_op": "-"}]}
    (body,) = dart_mcp.parse_events(payload, "cb_issuance")
    assert body.amount is None and body.conv_price is None
    assert body.use_of_funds == ()


def test_numbers_arrive_with_commas() -> None:
    payload = {"items": [{"rcept_no": "1", "bd_fta": "10,000,000,000"}]}
    (body,) = dart_mcp.parse_events(payload, "cb_issuance")
    assert body.amount == 10_000_000_000


def test_a_broken_number_is_dropped_not_raised() -> None:
    """상위가 형식을 바꿔도 그 칸만 비운다 — 본문 하나 때문에 종목이 죽으면 안 된다."""
    payload = {"items": [{"rcept_no": "1", "bd_fta": "약 100억", "cvisstk_tisstk_vs": "n/a"}]}
    (body,) = dart_mcp.parse_events(payload, "cb_issuance")
    assert body.amount is None and body.overhang_pct is None


def test_use_of_funds_lists_every_stated_purpose() -> None:
    payload = {
        "items": [
            {
                "rcept_no": "1",
                "fdpp_fclt": "1,000",
                "fdpp_op": "2,000",
                "fdpp_dtrp": "-",
                "fdpp_etc": "500",
            }
        ]
    }
    (body,) = dart_mcp.parse_events(payload, "cb_issuance")
    assert body.use_of_funds == (("시설자금", 1000), ("운영자금", 2000), ("기타자금", 500))


# ── 실패·빈 응답 ─────────────────────────────────────────────────


@pytest.mark.parametrize("payload", [{}, {"items": []}, {"items": None}])
def test_an_empty_payload_yields_nothing(payload: dict[str, object]) -> None:
    assert dart_mcp.parse_events(payload, "cb_issuance") == ()


def test_a_status_that_is_not_success_yields_nothing() -> None:
    """`status: 100`은 인자가 틀렸다는 뜻이다 — 빈 목록으로 조용히 넘기지 않는다."""
    payload = {"status": "100", "message": "필수값 누락", "items": []}
    assert dart_mcp.parse_events(payload, "cb_issuance") == ()


# ── 규칙 id → event_type 매핑 (F15) ──────────────────────────────


def test_every_mapped_rule_exists_in_the_rule_table() -> None:
    """없는 규칙을 매핑해 두면 영영 불리지 않는다."""
    from briefing import flags

    ids = {r.id for r in flags.RULES} | {flags.INSIDER_RULE}
    assert set(dart_mcp.EVENT_TYPE_OF) <= ids


def test_the_bond_rules_are_mapped() -> None:
    """전환사채·신주인수권부사채·교환사채·유상증자는 본문이 가장 값지다."""
    for rule, event in (
        ("cb", "cb_issuance"),
        ("bw", "bw_issuance"),
        ("eb", "eb_issuance"),
        ("rights_issue", "rights_offering"),
        ("capital_reduction", "capital_reduction"),
        ("lawsuit", "litigation"),
    ):
        assert dart_mcp.EVENT_TYPE_OF[rule] == event


def test_a_rule_without_a_mapping_is_simply_absent() -> None:
    """대응이 없으면 본문 없이 제목만 쓴다 — 없는 event_type을 지어내지 않는다."""
    assert "admin_issue" not in dart_mcp.EVENT_TYPE_OF
    assert dart_mcp.EVENT_TYPE_OF.get("delisting") is None
