"""verdict — 신호 검증 판정과 점수 (SPEC F18, v3.0). 순수 함수.

**점수는 코드가 낸다.** LLM에 숫자를 물으면 지어낸다 — 2026-08-30에 플래그 1건인 종목의
요약이 "위험 유형 2건"이라 적었다. 그래서 산식을 여기서 고정한다.

가중치를 바꾸면 이 테스트가 깨진다. 그것이 목적이다 — 점수가 조용히 달라지면
어제의 60과 오늘의 60이 다른 뜻이 된다.
"""

from __future__ import annotations

from datetime import date

import pytest

from briefing import verdict
from briefing.models import (
    Anomaly,
    Briefing,
    Disclosure,
    EventBody,
    Flag,
    FlowDay,
    InvestorFlows,
    NewsItem,
    SignalRow,
)

D = date(2026, 8, 26)


def brief(level: str = "none", **kw: object) -> Briefing:
    base: dict[str, object] = {
        "signal": SignalRow(d=D, strategy="mtf", ticker="413630", name="씨피시스템", evidence={}),
        "corp_code": "01601222",
        "level": level,
        "disclosures": (
            Disclosure(rcept_dt=D, report_nm="반기보고서 (2026.06)", rcept_no="p1", flr_nm="x"),
        ),
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


CB = Disclosure(
    rcept_dt=D, report_nm="주요사항보고서(전환사채권발행결정)", rcept_no="cb1", flr_nm="x"
)
CB_FLAG = Flag(rule="cb", level="red", rcept_no="cb1", report_nm=CB.report_nm)


def flows(*rows: tuple[int, int, int]) -> InvestorFlows:
    return InvestorFlows(
        days=tuple(FlowDay(d=date(2026, 8, day), inst=i, foreign=f) for day, i, f in rows)
    )


# ── 판정 세 가지 ─────────────────────────────────────────────────


def test_no_evidence_at_all_is_silent_at_neutral() -> None:
    """모르는 것을 낮은 점수로 바꾸지 않는다."""
    v = verdict.judge(brief(disclosures=()))
    assert v.stand == verdict.STAND_SILENT
    assert v.score == verdict.NEUTRAL
    assert v.parts == ()


def test_a_clean_filing_history_corroborates() -> None:
    v = verdict.judge(brief())
    assert v.stand == verdict.STAND_CORROBORATES
    assert v.score == verdict.NEUTRAL + verdict.W_NO_RISK


def test_a_big_overhang_contradicts() -> None:
    """엔투텍 08/26 — 잠재 물량 18.63%."""
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=18.63),),
        )
    )
    assert v.stand == verdict.STAND_CONTRADICTS
    assert v.score == verdict.NEUTRAL - 8 - 19  # 🔴 하나 + 오버행 19


def test_the_same_filing_title_scores_differently_by_its_body() -> None:
    """씨피시스템 08/26 — 5.10%. 엔투텍과 **제목이 같은데** 점수가 14점 벌어진다.

    판정은 둘 다 `불일치`지만 점수가 다르다. 그 차이가 본문을 읽는 이유다.
    """
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=5.10),),
        )
    )
    assert v.score == verdict.NEUTRAL - 8 - 5  # 37
    assert v.stand == verdict.STAND_CONTRADICTS
    assert v.score - (verdict.NEUTRAL - 8 - 19) == 14  # 엔투텍 23과의 거리


# ── 산식 고정 ────────────────────────────────────────────────────


def test_flag_penalty_has_a_floor() -> None:
    """플래그가 열 건이어도 감산은 하한에서 멈춘다 — 건수가 곧 위험도는 아니다."""
    flags = tuple(
        Flag(rule="cb", level="red", rcept_no=str(i), report_nm="x") for i in range(10)
    )
    v = verdict.judge(brief("red", disclosures=(CB,), flags=flags))
    (part,) = [p for p in v.parts if "위험 유형" in p.label]
    assert part.delta == verdict.FLAG_FLOOR


def test_overhang_penalty_has_a_cap() -> None:
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=90.0),),
        )
    )
    (part,) = [p for p in v.parts if "잠재 물량" in p.label]
    assert part.delta == verdict.W_OVERHANG_CAP


def test_refix_and_private_placement_each_subtract() -> None:
    body = EventBody(
        rcept_no="cb1", event_type="cb_issuance", refix_floor=1064, method="사모"
    )
    v = verdict.judge(brief("red", disclosures=(CB,), flags=(CB_FLAG,), bodies=(body,)))
    labels = {p.label: p.delta for p in v.parts}
    assert labels["시가하락 시 전환가 조정 조항"] == verdict.W_REFIX
    assert labels["사모 발행"] == verdict.W_PRIVATE


@pytest.mark.parametrize(
    ("state", "delta"), [("warning", -6), ("watch", -3), ("red_flag", -10), ("clean", 0)]
)
def test_anomaly_verdict_weights(state: str, delta: int) -> None:
    v = verdict.judge(brief(anomaly=Anomaly(score=1, verdict=state)))
    got = {p.label: p.delta for p in v.parts}
    if delta:
        assert got[f"공시 이상 {state}"] == delta
    else:
        assert not [p for p in v.parts if "공시 이상" in p.label]


def test_score_never_leaves_the_scale() -> None:
    flags = tuple(
        Flag(rule="cb", level="red", rcept_no=str(i), report_nm="x") for i in range(50)
    )
    body = EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=99.0, method="사모")
    v = verdict.judge(brief("red", disclosures=(CB,), flags=flags, bodies=(body,)))
    assert 0 <= v.score <= 100


# ── 수급 (F17) ───────────────────────────────────────────────────


def test_thirty_day_net_buying_adds() -> None:
    v = verdict.judge(brief(flows=flows((25, 10, 20), (26, 5, 5))))
    assert {p.label: p.delta for p in v.parts}["30일 기관·외국인 순매수"] == verdict.W_FLOW_30D


def test_thirty_day_net_selling_subtracts() -> None:
    v = verdict.judge(brief(flows=flows((25, -10, -20))))
    assert {p.label: p.delta for p in v.parts}["30일 기관·외국인 순매도"] == -verdict.W_FLOW_30D


def test_the_filing_day_is_weighed_separately() -> None:
    """씨피시스템: 5일 내내 외국인이 사다가 CB 공시일에 정확히 뒤집혔다."""
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            flows=flows((25, 0, 100), (26, -104_295, -1_139_791_314)),
        )
    )
    labels = {p.label: p.delta for p in v.parts}
    assert labels["08/26 공시일 기관·외국인 순매도"] == -verdict.W_FLOW_DAY


def test_a_day_with_no_flow_row_is_simply_skipped() -> None:
    v = verdict.judge(brief("red", disclosures=(CB,), flags=(CB_FLAG,), flows=flows((20, 1, 1))))
    assert not [p for p in v.parts if "공시일" in p.label]


# ── 사각지대 — 항상 함께 나간다 (R20) ────────────────────────────


def test_blind_spots_always_name_what_no_score_can_see() -> None:
    v = verdict.judge(brief())
    for word in verdict.ALWAYS_BLIND:
        assert word in v.blind_spots


def test_blind_spots_name_the_missing_layers_first() -> None:
    """수급도 뉴스도 없이 낸 점수라면 그렇게 적는다."""
    v = verdict.judge(brief())
    assert v.blind_spots[: 3] == ("수급", "뉴스", "공시 이상 점수")


def test_a_full_briefing_reports_only_the_permanent_blind_spots() -> None:
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance"),),
            news=(NewsItem(title="t", link="https://n"),),
            flows=flows((26, 1, 1)),
            anomaly=Anomaly(score=0, verdict="clean"),
        )
    )
    assert v.blind_spots == verdict.ALWAYS_BLIND


def test_the_limit_note_is_always_available() -> None:
    note = verdict.judge(brief()).limit_note
    assert "근거를 재며" in note and "실적·밸류에이션" in note


# ── 조회 실패·코드 미확인 ────────────────────────────────────────


@pytest.mark.parametrize("level", ["error", "unknown"])
def test_a_stock_we_could_not_look_up_is_silent(level: str) -> None:
    """공시를 못 봤으면 판정하지 않는다 — 침묵을 불일치로 바꾸지 않는다."""
    v = verdict.judge(brief(level))
    assert v.stand == verdict.STAND_SILENT and v.score == verdict.NEUTRAL and v.parts == ()


def test_the_stand_is_one_of_three() -> None:
    assert set(verdict.STANDS) == {"정합", "불일치", "무관"}
