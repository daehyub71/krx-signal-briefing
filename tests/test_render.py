"""render — 메일 제목·평문·HTML. 순수 함수 (SPEC F7·F8·N1·N2).

가장 중요한 것은 **문구 경계**다 (N1): 사실 나열은 되고 판단은 안 된다.
공시 제목·뉴스 제목은 **원문**이라 금지어 검사에서 뺀다 — 우리가 쓴 문장만 검사한다.
"""

from __future__ import annotations

import re
from datetime import date
from html import escape

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
    dart_link,
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
            out = out.replace(escape(d.report_nm), " ").replace(d.report_nm, " ")
        for n in b.news:
            out = out.replace(escape(n.title), " ").replace(n.title, " ")
    for b in briefings:
        out = out.replace(escape(b.name), " ").replace(b.name, " ")
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
        "amber",
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


def test_news_moved_to_the_web_page() -> None:
    """**메일은 간략하게** (D20 v2, 2026-08-31). 뉴스 목록은 웹 전문 페이지가 담는다.

    메일과 평문 모두 건수만 알리고 링크로 보낸다 — 15종목 × 5건이면 메일이 잘린다.
    """
    b = briefing(news=NEWS)
    assert escape(NEWS[0].title) not in render.html([b], D)
    assert "뉴스 1건" in render.text([b], D)


def test_news_absent_when_flagged() -> None:
    assert "📰" not in render.text([RED], D)
    assert "같은 기간 뉴스" not in render.html([RED], D)


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
    """한 줄 요약은 평문의 압축된 한 줄에서도 살아남는다 — 요약이 가장 값이 큰 문장이다."""
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
    b = briefing(disclosures=(odd,))
    assert odd.report_nm in render.html([b], D)
    assert odd.report_nm in render.text([briefing("amber", disclosures=(odd,))], D)


def test_forbidden_word_in_a_news_title_is_allowed() -> None:
    noisy = NewsItem(title="목표가 상향 소식에 매수세", link="https://n", published=D)
    # 메일에서 뉴스가 빠졌으므로(D20 v2) 원문 예외는 공시 제목으로 확인한다.
    odd = Disclosure(
        rcept_dt=D, report_nm="투자판단관련주요경영사항(매수청구)", rcept_no="9", flr_nm="x"
    )
    assert escape(odd.report_nm) in render.html([briefing(disclosures=(odd,))], D)
    assert noisy.title


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
    body = render.text([briefing("amber", disclosures=many)], D)
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


# ── HTML 레이아웃 (2026-08-29 시안 합의 · docs/DESIGN.md) ────────
#
# 지금까지 본문은 `<pre>` 한 덩어리였다. 위험 2건이 15종목 사이에 묻혔고,
# 공시마다 URL이 별도 줄로 나와 줄 수가 두 배였다 (2026-08-29 실측 — 18,012자).
# 아래 테스트가 새 레이아웃의 계약을 잠근다.


def many(n: int, level: str = "none") -> list[Briefing]:
    """압축·생략을 시험할 만큼 공시를 채운 브리핑 하나."""
    ds = tuple(
        Disclosure(
            rcept_dt=date(2026, 8, 20 - i),
            report_nm=f"공시제목{i}",
            rcept_no=f"2026082{i:07d}",
            flr_nm="가비아",
        )
        for i in range(n)
    )
    return [briefing(level, disclosures=ds)]


def test_html_puts_every_stock_in_the_index_table() -> None:
    """맨 위 인덱스 표가 15종목을 한 번에 훑는 **유일한** 자리다."""
    bs = [
        briefing("none"),
        Briefing.from_signal(sig("227950", "엔투텍"), "2", "none"),
        Briefing.from_signal(sig("413630", "씨피시스템"), "3", "none"),
    ]
    doc = render.html(bs, D)
    assert "한눈에 보기" in doc
    for b in bs:
        assert b.ticker in doc and b.name in doc


def test_html_disclosure_title_is_the_link_not_a_separate_url_line() -> None:
    """제목 자체가 링크다 — URL을 본문 텍스트로 다시 적지 않는다.

    예전에는 제목 아래 줄에 URL을 그대로 적어 줄 수가 두 배였다.
    """
    doc = render.html([RED], D)
    url = dart_link(CB.rcept_no)
    assert f'<a href="{url}"' in doc
    # href 속성을 지운 뒤에도 URL이 남아 있으면 = 본문에 URL을 또 적은 것
    without_hrefs = re.sub(r'href="[^"]*"', "", doc)
    assert url not in without_hrefs


def test_html_puts_the_contradicted_stocks_first() -> None:
    """v3.0은 등급이 아니라 **판정**으로 구역을 나눈다 (DESIGN §8).

    물음이 "위험이 있나"에서 "근거가 받치나"로 바뀌었다.
    """
    from briefing import verdict as vd

    calm = Briefing.from_signal(sig("227950", "엔투텍"), "2", "none")
    bs = [calm, RED]
    vs = {calm.ticker: vd.Verdict("정합", 68), RED.ticker: vd.Verdict("불일치", 20)}
    doc = render.html(bs, D, verdicts=vs)
    assert doc.index(render.SECTION_AGAINST) < doc.index(render.SECTION_REST_V3)


def test_html_compact_card_caps_disclosures_and_says_how_many_were_left_out() -> None:
    """위험 없는 종목은 압축 카드 — 공시 3건까지, 잘린 수는 드러낸다."""
    doc = render.html(many(9), D)
    assert doc.count("공시제목") == render.COMPACT_DISCLOSURES
    assert f"외 {9 - render.COMPACT_DISCLOSURES}건" in doc


def test_html_never_omits_a_flagged_disclosure() -> None:
    """플래그된 공시는 상한을 받지 않는다 — 그것 때문에 보내는 메일이다."""
    flagged = tuple(
        Disclosure(
            rcept_dt=date(2026, 8, 20),
            report_nm=f"주요사항보고서(전환사채권발행결정){i}",
            rcept_no=f"cb{i}",
            flr_nm="가비아",
        )
        for i in range(6)
    )
    b = briefing(
        "red",
        disclosures=flagged + (QUARTERLY,) * 8,
        flags=tuple(
            Flag(rule="cb", level="red", rcept_no=d.rcept_no, report_nm=d.report_nm)
            for d in flagged
        ),
    )
    doc = render.html([b], D)
    for d in flagged:
        assert d.report_nm in doc


def test_the_mail_no_longer_lists_news() -> None:
    """**메일은 간략하게** (D20 v2, 2026-08-31) — 뉴스는 웹이 담는다."""
    news = tuple(
        NewsItem(title=f"뉴스제목{i}", link=f"https://n/{i}", published=D) for i in range(7)
    )
    doc = render.html([briefing("none", news=news)], D)
    assert "뉴스제목" not in doc


def test_html_body_carries_no_emoji() -> None:
    """본문에서 이모지를 뺐다 — 클라이언트마다 다른 그림이 온다. 색 칩으로 바꿨다.

    제목(`subject`)의 🔴은 유지한다 — 받은편지함 목록에서 눈에 띄어야 한다.
    """
    doc = render.html([RED, briefing("none", news=NEWS)], D)
    for mark in ("🔴", "🟡", "📄", "📊", "💰", "📰", "👤", "💬"):
        assert mark not in doc, mark
    assert "🔴" in render.subject([RED], D)


def test_html_keeps_the_limit_note() -> None:
    """한계 문구는 어떤 경우에도 빠지지 않는다 (R7·N1)."""
    for doc in (
        render.html([RED], D),
        render.html([], D),
        render.html([], D, stale=True),
    ):
        assert render.LIMIT_NOTE in doc


def test_html_uses_no_forbidden_word_in_our_own_sentences() -> None:
    """원문(공시·뉴스 제목)을 지운 나머지 = 우리가 쓴 문장. 여기에 금지어가 없어야 한다."""
    odd = Disclosure(
        rcept_dt=D, report_nm="투자판단관련주요경영사항(매수청구)", rcept_no="9", flr_nm="x"
    )
    noisy = NewsItem(title="목표가 상향 소식에 매수세", link="https://n", published=D)
    bs = [RED, briefing("none", disclosures=(odd,), news=(noisy,))]
    ours = own_words(render.html(bs, D), bs)
    for word in render.FORBIDDEN:
        assert word not in ours, word


def test_html_shows_skipped_layers() -> None:
    """생략된 층은 조용히 빠지지 않는다 (D15)."""
    doc = render.html([briefing("none", skipped=("flow", "news"))], D)
    assert "시세 참고 생략" in doc and "뉴스 생략" in doc


def test_html_shows_the_summary_when_present() -> None:
    doc = render.html([briefing("none", summary="최근 30일 공시는 정기보고서뿐입니다")], D)
    assert "최근 30일 공시는 정기보고서뿐입니다" in doc


def test_html_reports_an_analysis_failure_without_hiding_the_evidence() -> None:
    """LLM이 죽어도 판정·공시·수급은 그대로 나간다 (F18·F19)."""
    doc = render.html([RED], D, summary_error="rate_limit")
    assert "근거 서술 생략" in doc and CB.report_nm in doc


def test_html_flag_labels_cover_every_rule() -> None:
    """규칙을 늘리고 라벨을 안 만들면 머리 밴드에 영어 id가 그대로 나온다."""
    from briefing import flags

    ids = {r.id for r in flags.RULES} | {flags.INSIDER_RULE}
    assert ids <= set(render.FLAG_LABELS)


def test_html_names_the_flagged_rule_in_plain_korean() -> None:
    doc = render.html([RED], D)
    assert render.FLAG_LABELS["cb"] in doc


def test_html_uses_tables_never_flex_or_grid() -> None:
    """Gmail은 flex·grid를 안드로이드에서 무너뜨린다 — 배치는 표로만 한다."""
    doc = render.html([RED, briefing("none", news=NEWS)], D)
    assert "<table" in doc
    assert "display:flex" not in doc and "display:grid" not in doc


def test_html_keeps_grade_colors_inline_so_they_survive_a_stripped_style_block() -> None:
    """되풀이되는 치수는 <style>로 접었다 — 하지만 **뜻이 있는 색은 inline이어야 한다**.

    <style>을 지우는 클라이언트가 있다. 지워지면 표는 밋밋해질 뿐이지만,
    등급 색까지 사라지면 위험 종목을 알아볼 수 없다.
    """
    doc = render.html([RED], D)
    body = doc.split("</style>", 1)[1]
    assert render.THEMES["red"][0] in body


def test_html_is_much_shorter_than_the_old_pre_block() -> None:
    """압축 카드의 존재 이유 — 15종목이 2만 자를 넘으면 읽히지 않는다."""
    bs = many(16) * 13 + [RED, RED]
    doc = render.html(bs, D)
    assert len(doc) < 60_000  # 마크업 포함. 본문 글자수는 이보다 훨씬 적다


def test_html_marks_a_corrected_disclosure() -> None:
    fixed = Disclosure(
        rcept_dt=D,
        report_nm="[기재정정]주요사항보고서(전환사채권발행결정)",
        rcept_no="fix1",
        flr_nm="가비아",
        corrected=True,
    )
    doc = render.html([briefing("none", disclosures=(fixed,))], D)
    assert "정정" in doc


def test_html_shows_market_cap_in_the_index() -> None:
    flow = Flow(
        bas_dd="20260827",
        close=4000,
        mktcap=145_746_420_000,
        list_shrs=36_436_605,
        trdval_5d=81_039_010_488,
        days=5,
    )
    doc = render.html([briefing("none", flow=flow)], D)
    assert "1,457억" in doc and "810억" in doc


def test_html_handles_unknown_and_error_levels() -> None:
    docs = render.html(
        [briefing("unknown", corp_code=None), briefing("error", error="HTTP 500")], D
    )
    assert render.UNKNOWN_WORDING in docs and render.ERROR_WORDING in docs


def test_html_head_band_carries_the_verdict_not_the_condition_count() -> None:
    """v3.0의 머리 밴드는 **판정**을 싣는다 — 조건 충족 수는 전문 페이지로 갔다 (DESIGN §8)."""
    from briefing import verdict as vd

    b = briefing("none")
    doc = render.html([b], D, verdicts={b.ticker: vd.Verdict("정합", 68)})
    assert "정합 68점" in doc


def test_html_stays_within_the_budget_by_folding_compact_cards_last() -> None:
    """예산을 넘으면 압축 카드부터 접는다 — Gmail이 잘라내면 꼬리 문구까지 사라진다.

    **접히지 않는 것이 설계다**: 인덱스 표(모든 종목)와 위험 종목 카드는 남는다.
    """
    bs = [RED] + many(14) * 40
    doc = render.html(bs, D)
    assert len(doc) <= render.HTML_BUDGET
    assert CB.report_nm in doc  # 위험 공시는 접히지 않는다
    assert "한눈에 보기" in doc
    assert render.LIMIT_NOTE in doc
    assert "위 「한눈에 보기」 표에 있습니다" in doc


def test_html_does_not_fold_anything_when_it_fits() -> None:
    doc = render.html([RED, briefing("none")], D)
    assert "표에 있습니다" not in doc


def test_real_sized_mail_fits_in_a_gmail_message() -> None:
    """실제 하루치(15종목·🔴 2) 크기의 메시지가 Gmail 클리핑에 걸리지 않아야 한다.

    2026-08-29: 전부 inline 스타일이던 첫 판이 149,971 bytes로 잘렸다. 그래서 이 테스트가 있다.
    """
    from email.message import EmailMessage

    bs = [RED, RED] + many(12) * 13
    msg = EmailMessage()
    msg["Subject"] = render.subject(bs, D)
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg.set_content(render.text(bs, D))
    msg.add_alternative(render.html(bs, D), subtype="html")
    assert len(bytes(msg)) < render.GMAIL_CLIP_BYTES


# ── 종목 블록 계약 (F7 · N2 · R8) ────────────────────────────────
#
# 상위 `ksa_signals.evidence`가 이 블록의 유일한 입력이다. 상위가 키를 바꾸거나
# 값 모양을 바꿔도 **메일 전체가 죽으면 안 된다** (R8) — 해당 줄만 비우고 계속 간다.


def sig_ev(ev: object) -> SignalRow:
    """evidence를 통째로 갈아끼운 신호 — R8 시험용."""
    return SignalRow(d=D, strategy="mtf", ticker="079940", name="가비아", evidence=ev)  # type: ignore[arg-type]


def test_block_renders_conditions_verbatim_and_in_order() -> None:
    """조건 줄은 `evidence.conditions`를 **그대로** 편다 — 상위 메일과 나란히 읽는다."""
    body = render.text([briefing("amber")], D)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip().startswith(("✓", "✗"))]
    assert lines == [
        "✓ 월봉 종가 > MA20 : 9,500 vs 4,581",
        "✓ 일봉 종가 > MA20 > MA60 : 8,420 > 8,407 > 7,490",
    ]


def test_block_marks_an_unmet_condition() -> None:
    ev = {"conditions": [{"label": "월봉 종가 > MA20", "ok": False, "actual": "9,500 vs 9,900"}]}
    b = Briefing.from_signal(sig_ev(ev), "1", "amber")
    assert "✗ 월봉 종가 > MA20 : 9,500 vs 9,900" in render.text([b], D)


def test_block_has_a_rule_between_the_signal_and_our_findings() -> None:
    """구분선 위는 상위가 보낸 것, 아래가 이 프로젝트의 산출물이다."""
    body = render.text([briefing("amber")], D)
    block = body[body.index("가비아 [079940]") :]
    i_cond = block.index("월봉 종가 > MA20")
    i_rule = block.index(render.RULE)
    i_grade = block.index("공시 1건")
    assert i_cond < i_rule < i_grade


def test_every_shown_disclosure_carries_its_source_link() -> None:
    """**원문 링크 필수** (N2) — 평문은 URL로, HTML은 제목에 건 앵커로.

    v3.0부터 정형 공시(`분기보고서`)는 HTML에서 한 줄로 접힌다 (F16) — 접힌 것은
    링크가 없지만 **건수는 항상 보인다.** 평문은 접지 않는다.
    """
    b = briefing("amber", disclosures=(CB, QUARTERLY))
    body = render.text([b], D)
    for d in (CB, QUARTERLY):
        assert dart_link(d.rcept_no) in body
    doc = render.html([b], D)
    assert f'<a href="{dart_link(CB.rcept_no)}"' in doc
    assert render.FOLDED_WORDING.format(n=1) in doc


# ── R8: evidence가 흔들려도 줄만 비운다 ──────────────────────────


def test_missing_evidence_empties_the_lines_but_keeps_the_block() -> None:
    """상위가 `evidence`를 통째로 비워도 종목 블록은 남는다 — 공시가 본체다."""
    b = Briefing.from_signal(sig_ev({}), "1", "none", disclosures=(QUARTERLY,))
    body = render.text([b], D)
    assert "가비아 [079940]" in body  # 종목 줄은 남는다
    assert "원 +" not in body  # 종가·등락은 비었다
    assert not [ln for ln in body.splitlines() if ln.strip().startswith(("✓", "✗"))]
    # 분기보고서는 정형이라 HTML에서 접힌다 (F16) — 접힌 건수로 확인한다.
    assert render.FOLDED_WORDING.format(n=1) in render.html([b], D)


def test_null_evidence_does_not_kill_the_mail() -> None:
    """DB가 `evidence`를 null로 주는 날이 있다 — 그날 메일이 통째로 죽으면 안 된다."""
    b = Briefing.from_signal(sig_ev(None), "1", "none", disclosures=(QUARTERLY,))
    assert "가비아" in render.text([b], D)
    assert "가비아" in render.html([b], D)


def test_condition_with_missing_keys_empties_only_that_line() -> None:
    """조건 항목에서 키가 빠지면 그 줄만 빈다 — 나머지 조건은 그대로 나온다."""
    ev = {
        "conditions": [
            {"label": "월봉 종가 > MA20", "ok": True, "actual": "9,500 vs 4,581"},
            {"ok": True},
        ]
    }
    b = Briefing.from_signal(sig_ev(ev), "1", "amber")
    body = render.text([b], D)
    assert "✓ 월봉 종가 > MA20 : 9,500 vs 4,581" in body
    assert "✓  : " in body


def test_price_that_is_not_a_number_falls_back_to_empty() -> None:
    """상위가 종가를 문자열로 바꿔 보내도 그 줄만 빈다 (R8).

    `int("8,420")`은 예외다 — 방어하지 않으면 그날 메일이 통째로 사라진다.
    """
    b = Briefing.from_signal(
        sig_ev({"price": {"close": "8,420", "change_pct": "n/a"}}), "1", "none"
    )
    assert "가비아 [079940]" in render.text([b], D)
    assert "가비아" in render.html([b], D)


def test_conditions_that_are_not_a_list_are_ignored() -> None:
    b = Briefing.from_signal(sig_ev({"conditions": "정배열"}), "1", "amber")
    body = render.text([b], D)
    assert not [ln for ln in body.splitlines() if ln.strip().startswith(("✓", "✗"))]


def test_a_real_sized_v3_mail_leaves_room(monkeypatch: pytest.MonkeyPatch) -> None:
    """v3.0은 카드에 본문 표·수급 표가 늘었다. 예산이 헐거우면 한계에 29 bytes까지 붙는다
    (2026-08-30 실측 102,371). 여유가 남는지 실제 `EmailMessage` 크기로 본다."""
    from email.message import EmailMessage

    from briefing import verdict as vd
    from briefing.models import EventBody, FlowDay, InvestorFlows

    long_reason = "가" * 600
    body = EventBody(
        rcept_no=CB.rcept_no, event_type="cb_issuance", amount=10_000_000_000,
        use_of_funds=(("시설자금", 10_000_000_000),), method="사모", coupon_rate=0.0,
        conv_price=5106, overhang_pct=5.10, outstanding=23_420_000_000,
    )
    flows = InvestorFlows(
        days=tuple(FlowDay(d=date(2026, 8, d), inst=1, foreign=-2, indiv=3) for d in range(1, 29))
    )
    bs = [
        briefing(
            "red", disclosures=(CB, QUARTERLY), flags=RED.flags, bodies=(body,),
            news=NEWS, flows=flows, summary=long_reason,
        )
        for _ in range(15)
    ]
    vs = {b.ticker: vd.Verdict("불일치", 23) for b in bs}
    msg = EmailMessage()
    msg["Subject"] = render.subject(bs, D)
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg.set_content(render.text(bs, D))
    msg.add_alternative(render.html(bs, D, verdicts=vs, page_url="https://x/y"), subtype="html")
    size = len(bytes(msg))
    # 이것은 **최악의 날**이다 — 15종목이 전부 불일치, 서술 600자, 조건 6줄.
    # 실제 08/26치는 77,560 bytes(여유 24%)였다. 최악에서도 10% 남아야 한다.
    assert size < render.GMAIL_CLIP_BYTES * 0.90, f"{size:,} bytes — 여유가 없다"
    # 접힌 것은 조용히 사라지지 않는다.
    doc = render.html(bs, D, verdicts=vs, page_url="https://x/y")
    assert "접었습니다" in doc
    # **어느 단계에서도 빠지지 않는 것** (R20)
    assert render.SCORE_LIMIT_NOTE.split(" — ")[0] in doc
    assert render.LIMIT_NOTE in doc
