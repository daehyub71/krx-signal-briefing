"""page — 전문 페이지 (SPEC F20 · DESIGN §8). 순수 함수.

메일에는 발췌만 싣고 전문은 여기로 보낸다 — 15종목 × 2,000자는 Gmail이 잘라낸다 (D20·N15).

**이 페이지는 본인 전용이다** (R7 v2). 판정과 점수를 남에게 배포하면
유사투자자문업 신고 대상이 된다. 그 경계를 테스트가 지킨다.
"""

from __future__ import annotations

import re
from datetime import date

from briefing import page, verdict
from briefing.models import (
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
EV = {
    "conditions": [{"label": "월봉 종가 > MA20", "ok": True, "actual": "3,770 vs 2,909"}],
    "price": {"close": 3980, "change_pct": 19.16},
}
CB = Disclosure(
    rcept_dt=D, report_nm="주요사항보고서(전환사채권발행결정)", rcept_no="cb1", flr_nm="씨피시스템"
)
CB_FLAG = Flag(rule="cb", level="red", rcept_no="cb1", report_nm=CB.report_nm)
BODY = EventBody(
    rcept_no="cb1",
    event_type="cb_issuance",
    decided_on="2026년 08월 26일",
    amount=10_000_000_000,
    use_of_funds=(("시설자금", 10_000_000_000),),
    method="사모",
    coupon_rate=0.0,
    conv_price=5106,
    overhang_pct=5.10,
    outstanding=23_420_000_000,
)
NEWS = (
    NewsItem(
        title="씨피시스템, 100억 규모 CB 발행…전액 제2공장 투입",
        link="https://n.news.naver.com/x",
        published=D,
        summary="조달자금은 전액 제2공장 설립에 필요한 시설투자에 사용될 예정이다.",
    ),
)
FLOWS = InvestorFlows(
    days=(
        FlowDay(d=date(2026, 8, 25), inst=64_565, foreign=56_140_446, indiv=-56_426_416),
        FlowDay(d=D, inst=-104_295, foreign=-1_139_791_314, indiv=1_131_306_196),
    )
)


def brief(**kw: object) -> Briefing:
    base: dict[str, object] = {
        "signal": SignalRow(
            d=D, strategy="mtf", ticker="413630", name="씨피시스템", evidence=EV
        ),
        "corp_code": "01601222",
        "level": "red",
        "disclosures": (CB,),
        "flags": (CB_FLAG,),
        "bodies": (BODY,),
        "news": NEWS,
        "flows": FLOWS,
        "summary": "판정은 불일치(23점)이다. 08/26 전환사채권 발행결정이 위험 유형 1건으로 걸렸다.",
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


def one(**kw: object) -> str:
    b = brief(**kw)
    return page.render([b], D, {b.ticker: verdict.judge(b)})


# ── 본인 전용 (R7 v2) ────────────────────────────────────────────


def test_the_page_says_not_to_share_it() -> None:
    """판정과 점수를 남에게 배포하면 유사투자자문업 신고 대상이다."""
    doc = one()
    assert "링크를 공유하지 마세요" in doc
    assert "유사투자자문업" in doc


def test_every_stock_repeats_what_the_score_cannot_see() -> None:
    """점수는 사실보다 그럴듯해 보인다 (R20) — 종목마다 한 번씩 적는다."""
    from briefing.render import SCORE_LIMIT_NOTE

    doc = one()
    assert doc.count(SCORE_LIMIT_NOTE) >= 1
    assert "매매 판단의 근거가 아닙니다" in doc


# ── 담는 것 ──────────────────────────────────────────────────────


def test_carries_the_full_analysis_not_an_excerpt() -> None:
    """메일은 발췌, 여기는 전문이다 — 그러려고 페이지를 만들었다."""
    long_text = "가" * 1800
    doc = one(summary=long_text)
    assert long_text in doc


def test_carries_the_filing_body_with_the_overhang() -> None:
    doc = one()
    assert "5.10%" in doc and "100억" in doc and "시설자금" in doc
    assert "사모" in doc and "5,106원" in doc


def test_sums_the_overhang_when_there_are_several_bodies() -> None:
    """여러 건이면 합산 잠재 물량이 핵심이다 — 엔투텍은 18.63% + 5.41% = 24.04%였다."""
    second = EventBody(rcept_no="cb2", event_type="cb_issuance", overhang_pct=5.41)
    first = EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=18.63)
    doc = one(bodies=(first, second))
    assert "24.04%" in doc


def test_marks_the_day_a_flagged_filing_landed_in_the_flow_table() -> None:
    """공시 당일 수급이 이 데이터를 모으는 이유다."""
    doc = one()
    assert "08/26" in doc and CB.report_nm in doc
    assert "-11.4억" in doc and "+11.3억" in doc


def test_carries_news_titles_with_their_summaries() -> None:
    doc = one()
    assert "제2공장" in doc


def test_carries_the_chart_conditions_that_were_checked() -> None:
    doc = one()
    assert "월봉 종가 &gt; MA20" in doc and "3,770 vs 2,909" in doc


def test_shows_how_the_score_was_reached() -> None:
    doc = one()
    assert "중립 50" in doc


# ── 목차·앵커 ────────────────────────────────────────────────────


def test_the_table_of_contents_links_to_each_stock() -> None:
    """메일의 `전문 보기 →`가 `#{ticker}`로 온다."""
    doc = one()
    assert 'href="#413630"' in doc and 'id="413630"' in doc


def test_the_table_of_contents_shows_verdict_and_length() -> None:
    doc = one()
    assert "23점" in doc or "점" in doc
    assert "자<" in doc  # 글자수


# ── 안전 ─────────────────────────────────────────────────────────


def test_escapes_names_and_titles() -> None:
    odd = Disclosure(rcept_dt=D, report_nm="M&A <주요사항>", rcept_no="cb1", flr_nm="x")
    b = Briefing.from_signal(
        SignalRow(d=D, strategy="mtf", ticker="413630", name="A&B", evidence=EV),
        "1",
        "red",
        disclosures=(odd,),
        summary="x",
    )
    doc = page.render([b], D, {})
    assert "A&amp;B" in doc and "<주요사항>" not in doc


def test_a_stock_without_analysis_still_shows_its_evidence() -> None:
    """LLM이 죽어도 판정·공시·수급은 나간다 (F18)."""
    doc = one(summary=None)
    assert "근거 서술이 없습니다" in doc
    assert "5.10%" in doc


def test_an_empty_day_renders_without_crashing() -> None:
    doc = page.render([], D, {})
    assert "링크를 공유하지 마세요" in doc


def test_the_page_has_no_forbidden_word_in_our_own_sentences() -> None:
    """원문(공시·뉴스 제목·분석문)을 지운 나머지 = 우리가 쓴 문장 (N1 v2)."""
    from briefing.render import FORBIDDEN

    b = brief()
    doc = page.render([b], D, {b.ticker: verdict.judge(b)})
    ours = doc
    for d in b.disclosures:
        ours = ours.replace(d.report_nm, " ")
    for n in b.news:
        ours = ours.replace(n.title, " ").replace(n.summary, " ")
    ours = ours.replace(b.summary or "", " ").replace(b.name, " ")
    from briefing.render import has_forbidden

    assert not has_forbidden(ours), has_forbidden(ours)
    assert FORBIDDEN  # 목록이 비면 검사가 무의미해진다


def test_the_page_is_one_self_contained_document() -> None:
    """외부 스타일시트·스크립트를 부르지 않는다 — 어디서 열어도 같아야 한다."""
    doc = one()
    assert "<script" not in doc
    assert not re.search(r'<link[^>]+stylesheet', doc)
