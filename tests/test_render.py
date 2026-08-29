"""render — 메일 제목·평문·HTML. 순수 함수 (SPEC F7·F8·N1·N2).

가장 중요한 것은 **문구 경계**다 (N1): 사실 나열은 되고 판단은 안 된다.
공시 제목·뉴스 제목은 **원문**이라 금지어 검사에서 뺀다 — 우리가 쓴 문장만 검사한다.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from briefing import render
from briefing.models import (
    Anomaly,
    Briefing,
    Disclosure,
    Flag,
    Flow,
    Insider,
    NewsItem,
    SignalRow,
)

D = date(2026, 8, 25)
EV = {
    "conditions": [
        {"label": "월봉 종가 > MA20", "ok": True, "actual": "9,500 vs 4,581"},
        {"label": "일봉 종가 > MA20 > MA60", "ok": True, "actual": "8,420 > 8,407 > 7,490"},
    ],
    "price": {"close": 8420, "change_pct": 1.32},
    "meta": {"in_progress": False},
}
CB = Disclosure(
    rcept_dt=date(2026, 8, 22),
    report_nm="주요사항보고서(전환사채권발행결정)",
    rcept_no="20260822000123",
    flr_nm="가비아",
)
QUARTERLY = Disclosure(
    rcept_dt=date(2026, 8, 7), report_nm="분기보고서 (2026.03)", rcept_no="2", flr_nm="가비아"
)
NEWS = (
    NewsItem(
        title="맥쿼리 공개매수 중인 가비아, 이사 선임 놓고 얼라인과 '표 대결' 전망",
        link="https://n.news.naver.com/x",
        origin="https://biz.example.com/1",
        published=date(2026, 8, 28),
    ),
)


def sig(ticker: str = "079940", name: str = "가비아", strategy: str = "mtf") -> SignalRow:
    return SignalRow(d=D, strategy=strategy, ticker=ticker, name=name, evidence=EV)


def briefing(level: str = "none", **kw: object) -> Briefing:
    base: dict[str, object] = {
        "signal": sig(),
        "corp_code": "00506294",
        "level": level,
        "disclosures": (QUARTERLY,),
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


RED = briefing(
    "red",
    flags=(Flag(rule="cb", level="red", rcept_no=CB.rcept_no, report_nm=CB.report_nm),),
    disclosures=(CB, QUARTERLY),
)


def own_words(body: str, briefings: list[Briefing]) -> str:
    """본문에서 **원문**(공시 제목·뉴스 제목·종목명)을 지운 나머지 — 우리가 쓴 문장.

    제목을 **먼저** 통째로 지운 뒤 종목명을 지운다. 순서를 뒤집으면 제목 안의 종목명이
    먼저 사라져 제목 매칭이 깨지고, 남은 조각이 금지어로 잡힌다.
    """
    out = body
    for b in briefings:
        for d in b.disclosures:
            out = out.replace(d.report_nm, " ")
        for n in b.news:
            out = out.replace(n.title, " ")
    for b in briefings:
        out = out.replace(b.name, " ")
    return out


# ── 제목 (F8) ────────────────────────────────────────────────────


def test_subject_counts_by_level() -> None:
    s = render.subject([RED, briefing("amber"), briefing(), briefing()], D)
    assert s.startswith("[브리핑] 08/25")
    assert "🔴 1" in s and "🟡 1" in s and "확인된 위험 유형 없음 2" in s


def test_subject_when_no_signals() -> None:
    assert render.subject([], D) == "[브리핑 없음] 08/25"


def test_subject_when_stale() -> None:
    s = render.subject([], D, stale=True)
    assert s.startswith("[브리핑 없음] 08/25") and "데이터 지연" in s


def test_subject_prefixes_errors() -> None:
    s = render.subject([RED, briefing("error")], D)
    assert s.startswith("⚠ 공시 조회 실패 1건 · ")


# ── 종목 블록 (F7) ───────────────────────────────────────────────


def test_block_keeps_signal_conditions_verbatim() -> None:
    body = render.text([RED], D)
    assert "월봉 종가 > MA20 : 9,500 vs 4,581" in body
    assert "일봉 종가 > MA20 > MA60 : 8,420 > 8,407 > 7,490" in body
    assert "가비아 [079940] 8,420원 +1.32%" in body


def test_block_lists_every_disclosure_with_a_link() -> None:
    """모든 공시 항목에 원문 링크 (N2)."""
    body = render.text([RED], D)
    for d in (CB, QUARTERLY):
        assert d.report_nm in body
        assert f"rcpNo={d.rcept_no}" in body


def test_none_level_wording_is_not_no_risk() -> None:
    """'없다'가 아니라 '확인된 항목 없음' (N1)."""
    body = render.text([briefing()], D)
    assert "최근 30일 공시 중 확인된 위험 유형 없음" in body
    assert "리스크 없음" not in body


def test_red_summary_block_lists_flagged_names_first() -> None:
    body = render.text([briefing(), RED], D)
    head = body.split("가비아 [079940]")[0]
    assert "🔴" in head and "가비아" in head  # 상단 요약에 먼저 나온다


def test_unknown_and_error_are_marked() -> None:
    body = render.text(
        [briefing("unknown", corp_code=None), briefing("error", error="타임아웃")], D
    )
    assert "DART 코드 미확인" in body and "공시 조회 실패" in body


# ── 보조 신호 · 시세 · 뉴스 ──────────────────────────────────────


def test_side_signals_are_shown_as_reference() -> None:
    b = briefing(
        anomaly=Anomaly(score=68, verdict="warning", summary="정정공시 42/2000건"),
        insider=Insider(
            signal="sell_cluster", sell_events=4, unique_sellers=3, net_change_shares=-900
        ),
        flow=Flow(
            bas_dd="20260825",
            close=8420,
            mktcap=611_312_156_200,
            list_shrs=13_420_684,
            trdval_5d=3_250_819_650,
            days=5,
        ),
    )
    body = render.text([b], D)
    assert "68/100" in body and "warning" in body
    assert "매도" in body and "3명" in body
    assert "시총 6,113억" in body


def test_news_block_lists_title_date_and_link() -> None:
    body = render.text([briefing(news=NEWS)], D)
    assert "📰" in body
    assert NEWS[0].title in body
    assert "08/28" in body and NEWS[0].link in body


def test_news_absent_when_flagged() -> None:
    assert "📰" not in render.text([RED], D)


@pytest.mark.parametrize(
    ("skipped", "mark"),
    [
        (("anomaly",), "보조 신호 생략"),
        (("news",), "뉴스 생략"),
        (("flow",), "시세 참고 생략"),
        (("anomaly", "insider", "news", "flow"), "뉴스 생략"),
    ],
)
def test_skipped_layers_are_marked(skipped: tuple[str, ...], mark: str) -> None:
    body = render.text([briefing(skipped=skipped)], D)
    assert mark in body and "⚠" in body


def test_summary_failure_is_marked() -> None:
    body = render.text([briefing()], D, summary_error="APIConnectionError")
    assert "⚠ 요약 생성 실패" in body


def test_summary_line_is_shown_when_present() -> None:
    body = render.text([briefing(summary="08/22 CB 발행 결정 — 위험 유형 1건")], D)
    assert "💬 08/22 CB 발행 결정 — 위험 유형 1건" in body


# ── 금지어 (N1) — 우리가 쓴 문장만 검사 ─────────────────────────


def test_our_own_words_carry_no_judgement() -> None:
    bs = [RED, briefing("amber"), briefing(news=NEWS), briefing("unknown", corp_code=None)]
    body = own_words(render.text(bs, D), bs)
    for word in render.FORBIDDEN:
        assert word not in body, f"금지어 '{word}'가 본문에 있다"


def test_forbidden_word_in_a_disclosure_title_is_allowed() -> None:
    """공시 제목은 원문이다 — 금지어가 들어 있어도 그대로 싣는다."""
    odd = Disclosure(
        rcept_dt=D, report_nm="투자판단관련주요경영사항(매수청구)", rcept_no="9", flr_nm="x"
    )
    body = render.text([briefing(disclosures=(odd,))], D)
    assert odd.report_nm in body


def test_forbidden_word_in_a_news_title_is_allowed() -> None:
    noisy = NewsItem(title="목표가 상향 소식에 매수세", link="https://n", published=D)
    body = render.text([briefing(news=(noisy,))], D)
    assert noisy.title in body


# ── HTML · 평문 ─────────────────────────────────────────────────


def test_html_escapes_company_and_disclosure_names() -> None:
    amp = Disclosure(rcept_dt=D, report_nm="M&A 관련 <주요사항>", rcept_no="7", flr_nm="x")
    b = Briefing.from_signal(sig(name="A&B"), "1", "none", disclosures=(amp,))
    doc = render.html([b], D)
    assert "A&amp;B" in doc and "M&amp;A 관련 &lt;주요사항&gt;" in doc
    assert "<주요사항>" not in doc.replace("&lt;주요사항&gt;", "")


def test_html_links_are_anchors() -> None:
    doc = render.html([RED], D)
    assert f'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo={CB.rcept_no}"' in doc


def test_html_and_text_cover_the_same_stocks() -> None:
    bs = [RED, briefing(news=NEWS)]
    doc, body = render.html(bs, D), render.text(bs, D)
    for b in bs:
        assert b.ticker in doc and b.ticker in body


def test_text_has_no_html_tags() -> None:
    body = render.text([RED, briefing(news=NEWS)], D)
    assert not re.search(r"<[a-z/][^>]*>", body)


def test_empty_briefings_still_produce_a_body() -> None:
    body = render.text([], D)
    assert "브리핑 대상 없음" in body and "신호" in body


def test_stale_body_explains_why() -> None:
    body = render.text([], D, stale=True)
    assert "데이터 지연" in body


# ── 길이 제한 — 플래그된 공시는 예외 ─────────────────────────────


def test_plain_disclosures_are_capped_with_a_note() -> None:
    """15종목 × 16건이면 2만 자가 넘는다 (실측). 잘린 사실은 드러낸다."""
    many = tuple(
        Disclosure(
            rcept_dt=date(2026, 8, 20 - i % 10),
            report_nm=f"분기보고서{i}",
            rcept_no=str(i),
            flr_nm="x",
        )
        for i in range(16)
    )
    body = render.text([briefing(disclosures=many)], D)
    shown = body.count("분기보고서")
    assert shown == render.PLAIN_DISCLOSURES
    assert f"외 {16 - render.PLAIN_DISCLOSURES}건" in body


def test_flagged_disclosures_are_never_omitted() -> None:
    """🔴가 잘리면 메일을 보내는 이유가 사라진다."""
    noise = tuple(
        Disclosure(rcept_dt=D, report_nm=f"기업설명회{i}", rcept_no=f"n{i}", flr_nm="x")
        for i in range(12)
    )
    b = briefing(
        "red",
        disclosures=(*noise, CB),
        flags=(Flag(rule="cb", level="red", rcept_no=CB.rcept_no, report_nm=CB.report_nm),),
    )
    body = render.text([b], D)
    assert CB.report_nm in body and f"rcpNo={CB.rcept_no}" in body
    assert "외 8건" in body
