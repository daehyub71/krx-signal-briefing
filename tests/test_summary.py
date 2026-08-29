"""summary — LLM 입력 구성·응답 검증 (F14·N13). 순수 함수, LLM 없이 검사한다."""

from __future__ import annotations

from datetime import date

import pytest

from briefing import summary
from briefing.models import Anomaly, Briefing, Disclosure, Flag, NewsItem, SignalRow

D = date(2026, 8, 25)
CB = Disclosure(
    rcept_dt=date(2026, 8, 22),
    report_nm="주요사항보고서(전환사채권발행결정)",
    rcept_no="1",
    flr_nm="가비아",
)
QUARTERLY = Disclosure(
    rcept_dt=date(2026, 8, 7), report_nm="분기보고서 (2026.03)", rcept_no="2", flr_nm="가비아"
)
NEWS = (
    NewsItem(title="맥쿼리 공개매수 중인 가비아", link="https://n/1", published=date(2026, 8, 28)),
)


def brief(
    level: str = "red", ticker: str = "079940", name: str = "가비아", **kw: object
) -> Briefing:
    base: dict[str, object] = {
        "signal": SignalRow(d=D, strategy="mtf", ticker=ticker, name=name),
        "corp_code": "1",
        "level": level,
        "disclosures": (CB, QUARTERLY),
        "flags": (Flag(rule="cb", level="red", rcept_no="1", report_nm=CB.report_nm),),
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


# ── 입력 구성 ────────────────────────────────────────────────────


def test_build_input_skips_stocks_without_material() -> None:
    """공시도 뉴스도 없으면 요약할 것이 없다 — LLM에 보내지 않는다."""
    items = summary.build_input([brief("none", disclosures=(), flags=())])
    assert items == []


def test_build_input_includes_titles_dates_and_level() -> None:
    items = summary.build_input([brief()])
    assert len(items) == 1
    it = items[0]
    assert it["ticker"] == "079940" and it["name"] == "가비아" and it["level"] == "red"
    assert it["disclosures"] == [
        {"date": "08/22", "title": CB.report_nm},
        {"date": "08/07", "title": QUARTERLY.report_nm},
    ]
    assert "news" not in it  # 뉴스가 없으면 키 자체를 넣지 않는다


def test_build_input_includes_news_titles() -> None:
    """등급 none 종목의 뉴스 제목도 입력에 넣는다 — 본문은 넣지 않는다 (F14)."""
    items = summary.build_input([brief("none", flags=(), disclosures=(QUARTERLY,), news=NEWS)])
    assert items[0]["news"] == [{"date": "08/28", "title": NEWS[0].title}]
    assert all("link" not in n for n in items[0]["news"])


def test_build_input_carries_anomaly_verdict_only() -> None:
    items = summary.build_input(
        [brief(anomaly=Anomaly(score=68, verdict="warning", summary="긴 설명"))]
    )
    assert items[0]["anomaly"] == {"score": 68, "verdict": "warning"}


def test_build_input_skips_error_and_unknown() -> None:
    assert summary.build_input([brief("error"), brief("unknown")]) == []


def test_build_input_caps_disclosures_per_stock() -> None:
    many = tuple(
        Disclosure(rcept_dt=D, report_nm=f"공시{i}", rcept_no=str(i), flr_nm="x") for i in range(30)
    )
    items = summary.build_input([brief(disclosures=many)])
    assert len(items[0]["disclosures"]) == summary.MAX_DISCLOSURES


def test_system_prompt_states_the_rules() -> None:
    p = summary.SYSTEM_PROMPT
    for must in ("사실", "입력에 없는", "80자", "등급"):
        assert must in p


def test_schema_shape() -> None:
    assert summary.OUTPUT_SCHEMA["type"] == "object"
    assert "items" in summary.OUTPUT_SCHEMA["properties"]


# ── 응답 검증 (N13) ──────────────────────────────────────────────


def test_validate_keeps_good_items() -> None:
    kept, dropped = summary.validate(
        {"items": [{"ticker": "079940", "summary": "08/22 전환사채 발행 결정 — 위험 유형 1건"}]},
        ["079940"],
    )
    assert kept == {"079940": "08/22 전환사채 발행 결정 — 위험 유형 1건"} and dropped == []


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ({"ticker": "079940", "summary": "지금이 매수 기회"}, "금지어"),
        ({"ticker": "079940", "summary": "가" * 81}, "길이"),
        ({"ticker": "000000", "summary": "입력에 없는 종목"}, "미지 티커"),
        ({"ticker": "079940", "summary": "   "}, "빈 문자열"),
        ({"summary": "티커 없음"}, "티커 없음"),
    ],
)
def test_validate_drops_bad_items_with_reason(bad: dict[str, str], why: str) -> None:
    kept, dropped = summary.validate({"items": [bad]}, ["079940"])
    assert kept == {} and len(dropped) == 1 and why in dropped[0]


def test_validate_keeps_the_good_and_drops_the_bad() -> None:
    kept, dropped = summary.validate(
        {
            "items": [
                {"ticker": "079940", "summary": "정상 요약"},
                {"ticker": "222040", "summary": "매도 권고"},
            ]
        },
        ["079940", "222040"],
    )
    assert list(kept) == ["079940"] and len(dropped) == 1


def test_validate_handles_garbage_payload() -> None:
    assert summary.validate({}, ["079940"]) == ({}, [])
    assert summary.validate({"items": "not a list"}, ["079940"]) == ({}, [])
