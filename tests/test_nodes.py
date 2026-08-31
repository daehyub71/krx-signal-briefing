"""nodes — I/O 노드의 상태 매핑. store는 전부 스텁."""

from __future__ import annotations

from datetime import date

import pytest

from briefing import nodes, store
from briefing.state import GATE_MISSING, GATE_READY, GATE_STALE, initial_state

RUN_DATE = date(2026, 8, 26)
DATA_DATE = date(2026, 8, 25)


@pytest.fixture
def no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "conn", lambda: object())


def test_gate_ready_when_run_recorded(no_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (DATA_DATE, "ok"))
    out = nodes.gate(initial_state(RUN_DATE))
    assert out == {"gate": GATE_READY, "data_date": DATA_DATE}


@pytest.mark.parametrize("status", ["partial_send_failed", "send_failed"])
def test_gate_ready_even_if_upstream_send_failed(
    no_db: None, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    """상위는 저장 후 발송한다 — 발송이 실패해도 신호는 있다 (F1)."""
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (DATA_DATE, status))
    assert nodes.gate(initial_state(RUN_DATE))["gate"] == GATE_READY


def test_gate_stale_when_upstream_had_stale_data(
    no_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: (None, "stale_data"))
    out = nodes.gate(initial_state(RUN_DATE))
    assert out["gate"] == GATE_STALE and out["data_date"] is None


def test_gate_missing_when_no_row(no_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "fetch_today_run", lambda c, d: None)
    out = nodes.gate(initial_state(RUN_DATE))
    assert out == {"gate": GATE_MISSING, "data_date": None}


# ── fetch_one — 멱등 · unknown · MCP→REST 폴백 · 보조 신호 생략 · error (F3·F4·F4b·F5) ──

from datetime import timedelta  # noqa: E402
from typing import cast  # noqa: E402

from briefing import dart, dart_mcp, mcpc, news_mcp  # noqa: E402
from briefing.models import Anomaly, Briefing, Disclosure, Insider, SignalRow  # noqa: E402
from briefing.state import FetchItem  # noqa: E402

SIG = SignalRow(d=DATA_DATE, strategy="mtf", ticker="079940", name="가비아")
CB = Disclosure(
    rcept_dt=date(2026, 8, 22),
    report_nm="[기재정정]주요사항보고서(전환사채권발행결정)",
    rcept_no="1",
    flr_nm="가비아",
)
QUARTERLY = Disclosure(
    rcept_dt=date(2026, 8, 7), report_nm="분기보고서 (2026.03)", rcept_no="2", flr_nm="가비아"
)
ANOMALY = Anomaly(score=12, verdict="clean")
INSIDER_SELL = Insider(
    signal="sell_cluster", sell_events=4, unique_sellers=3, net_change_shares=-900
)


def fetch_item(**kw: object) -> FetchItem:
    base: dict[str, object] = {
        "signal": SIG,
        "corp_code": "00506294",
        "existing": None,
        "force": False,
        "run_date": RUN_DATE,
    }
    base.update(kw)
    return cast(FetchItem, base)


class Spy:
    """호출 기록 + 정해진 결과/예외."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object, **kw: object) -> object:
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> dict[str, Spy]:
    """기본: MCP 정상(CB+분기) · REST 미사용 · anomaly·insider 정상. 테스트가 개별로 바꾼다."""
    spies = {
        "mcp": Spy([CB, QUARTERLY]),
        "rest": Spy([QUARTERLY]),
        "anomaly": Spy(ANOMALY),
        "insider": Spy(Insider(signal="none")),
        "news": Spy([]),  # 등급 none이면 뉴스도 부른다 (F11) — 기본은 0건
    }
    monkeypatch.setattr(dart_mcp, "fetch_disclosures", spies["mcp"])
    monkeypatch.setattr(dart, "fetch_disclosures", spies["rest"])
    monkeypatch.setattr(dart_mcp, "fetch_anomaly", spies["anomaly"])
    monkeypatch.setattr(dart_mcp, "fetch_insider", spies["insider"])
    monkeypatch.setattr(news_mcp, "fetch_news", spies["news"])
    return spies


def test_fetch_one_reuses_existing_without_dart(sources: dict[str, Spy]) -> None:
    """그날 브리핑이 이미 있으면 DART를 다시 부르지 않는다 (N6)."""
    existing = Briefing.from_signal(SIG, "00506294", "red")
    out = nodes.fetch_one(fetch_item(existing=existing))
    assert out == {"briefings": [existing], "dart_calls": 0}
    assert all(spy.calls == [] for spy in sources.values())


def test_fetch_one_force_refetches(sources: dict[str, Spy]) -> None:
    existing = Briefing.from_signal(SIG, "00506294", "red")
    out = nodes.fetch_one(fetch_item(existing=existing, force=True))
    assert len(sources["mcp"].calls) == 1 and out["briefings"][0].level == "red"


def test_fetch_one_unknown_when_no_corp_code(sources: dict[str, Spy]) -> None:
    out = nodes.fetch_one(fetch_item(corp_code=None))
    b = out["briefings"][0]
    assert b.level == "unknown" and b.corp_code is None and out["dart_calls"] == 0
    assert all(spy.calls == [] for spy in sources.values())


def test_fetch_one_mcp_path_classifies_and_uses_window(sources: dict[str, Spy]) -> None:
    out = nodes.fetch_one(fetch_item())
    b = out["briefings"][0]
    assert sources["mcp"].calls == [("00506294", RUN_DATE - timedelta(days=30), RUN_DATE)]
    assert sources["rest"].calls == []  # 폴백 없음
    assert b.source == "mcp" and b.skipped == ("investor_flows",)
    assert b.level == "red" and [f.rule for f in b.flags] == ["cb"]
    assert [d.corrected for d in b.disclosures] == [True, False]
    assert b.anomaly == ANOMALY and b.insider is not None and b.insider.signal == "none"
    assert out["dart_calls"] == 1


def test_fetch_one_falls_back_to_rest_when_mcp_fails(sources: dict[str, Spy]) -> None:
    """korean-dart-mcp가 죽어도 메일은 간다 (D15) — REST로 공시를 받고 보조 신호는 생략 표기."""
    sources["mcp"].result = mcpc.McpStartError("[dart] 기동 실패")
    sources["anomaly"].result = mcpc.McpUnavailableError("[dart] 사용 불가")
    sources["insider"].result = mcpc.McpUnavailableError("[dart] 사용 불가")
    out = nodes.fetch_one(fetch_item())
    b = out["briefings"][0]
    assert sources["rest"].calls == [("00506294", RUN_DATE - timedelta(days=30), RUN_DATE)]
    assert b.source == "rest" and b.level == "none"  # REST 결과(분기보고서만)로 판정
    assert b.anomaly is None and b.insider is None
    assert b.skipped == ("anomaly", "insider", "investor_flows")  # 뉴스는 살아 있어 생략되지 않는다
    assert out["dart_calls"] == 1


def test_fetch_one_error_when_mcp_and_rest_both_fail(sources: dict[str, Spy]) -> None:
    sources["mcp"].result = mcpc.McpCallError("[dart] 타임아웃")
    sources["rest"].result = dart.DartRateLimitError("020 한도", "020")
    out = nodes.fetch_one(fetch_item())
    b = out["briefings"][0]
    assert b.level == "error" and "020" in b.error and out["dart_calls"] == 1
    assert sources["anomaly"].calls == []  # 공시를 못 받았으면 보조 신호도 안 부른다


def test_fetch_one_skips_only_the_failed_side_signal(sources: dict[str, Spy]) -> None:
    """anomaly가 죽어도 insider는 살아서 🟡 플래그를 단다."""
    sources["anomaly"].result = ValueError("응답에 score 없음")
    sources["insider"].result = INSIDER_SELL
    b = nodes.fetch_one(fetch_item(signal=SIG))["briefings"][0]
    assert b.anomaly is None and b.skipped == ("anomaly", "investor_flows")
    assert b.insider == INSIDER_SELL
    assert b.level == "red" and [f.rule for f in b.flags] == ["cb", "insider_sell_cluster"]


def test_fetch_one_insider_sell_cluster_raises_none_to_amber(sources: dict[str, Spy]) -> None:
    sources["mcp"].result = [QUARTERLY]
    sources["insider"].result = INSIDER_SELL
    b = nodes.fetch_one(fetch_item())["briefings"][0]
    assert b.level == "amber" and [f.rule for f in b.flags] == ["insider_sell_cluster"]


def test_fetch_one_applies_reit_exception(sources: dict[str, Spy]) -> None:
    reit = SignalRow(d=DATA_DATE, strategy="mtf", ticker="417310", name="코람코더원리츠")
    sources["mcp"].result = [
        Disclosure(
            rcept_dt=date(2026, 8, 20),
            report_nm="주요사항보고서(유상증자결정)",
            rcept_no="9",
            flr_nm="코람코더원리츠",
        )
    ]
    b = nodes.fetch_one(fetch_item(signal=reit, corp_code="00333333"))["briefings"][0]
    assert b.level == "amber"


def test_fetch_one_is_thin() -> None:
    """노드는 20줄을 넘지 않는다 (N11)."""
    import inspect

    body = inspect.getsource(nodes.fetch_one).split('"""')[-1]  # docstring 뒤
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) <= 20, len(lines)


# ── load_market — 시세 참고 배치 1회 (F12) · fetch_one ③ flow 부착 ─────────

from briefing.models import Flow  # noqa: E402

FLOW = Flow(
    bas_dd="20260828",
    close=46000,
    mktcap=125_948_000_000,
    list_shrs=2_738_000,
    trdval_5d=5_201_000_000,
    days=2,
)


def test_load_market_reads_from_upstream_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """외부 호출 없음 — 상위가 채운 ksc_tickers·ksc_bars를 SQL 한 번으로 읽는다 (D14 v2)."""
    spy = Spy({"079940": FLOW})
    monkeypatch.setattr(store, "conn", lambda: "CONN")
    monkeypatch.setattr(store, "fetch_flows", spy)
    monkeypatch.setattr(store, "fetch_flows_30d", lambda c, t: {})
    state = initial_state(RUN_DATE)
    state["signals"] = [
        SIG,
        SignalRow(d=DATA_DATE, strategy="vcp", ticker="079940", name="가비아"),
        SignalRow(d=DATA_DATE, strategy="mtf", ticker="005930", name="삼성전자"),
    ]
    out = nodes.load_market(state)
    assert spy.calls == [("CONN", ["005930", "079940"])]  # 종목 중복 제거 · 정렬
    assert out["flows"] == {"079940": FLOW} and out["flow_skipped"] == ""


def test_load_market_skips_when_query_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """시세는 참고 층이다 — DB 오류가 메일을 막지 않는다."""
    monkeypatch.setattr(store, "conn", lambda: "CONN")
    monkeypatch.setattr(store, "fetch_flows", Spy(RuntimeError("연결 끊김")))
    state = initial_state(RUN_DATE)
    state["signals"] = [SIG]
    out = nodes.load_market(state)
    assert out["flows"] == {} and "실패" in out["flow_skipped"]


def test_load_market_marks_skipped_when_upstream_has_no_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "conn", lambda: "CONN")
    monkeypatch.setattr(store, "fetch_flows", Spy({}))
    monkeypatch.setattr(store, "fetch_flows_30d", lambda c, t: {})
    state = initial_state(RUN_DATE)
    state["signals"] = [SIG]
    out = nodes.load_market(state)
    assert out["flows"] == {} and "시총" in out["flow_skipped"]


def test_fan_out_passes_flow_per_ticker() -> None:
    state = initial_state(RUN_DATE)
    state["signals"] = [SIG]
    state["flows"] = {"079940": FLOW}
    sends = nodes.fan_out(state)
    assert not isinstance(sends, str)
    item = sends[0].arg
    assert item["flow"] == FLOW and item["flow_skipped"] is False


def test_fetch_one_attaches_flow(sources: dict[str, Spy]) -> None:
    b = nodes.fetch_one(fetch_item(flow=FLOW, flow_skipped=False))["briefings"][0]
    assert b.flow == FLOW and "flow" not in b.skipped


def test_fetch_one_marks_flow_skipped(sources: dict[str, Spy]) -> None:
    """키 없음·서버 미기동 → 전 종목 `skipped`에 flow — 본문에 ⚠ 시세 참고 생략."""
    b = nodes.fetch_one(fetch_item(flow=None, flow_skipped=True))["briefings"][0]
    assert b.flow is None and b.skipped == ("flow", "investor_flows")


def test_fetch_one_flow_missing_but_layer_alive_is_not_skipped(sources: dict[str, Spy]) -> None:
    """시세 층은 살았는데 이 종목만 KRX에 없음(비상장·KONEX) — 생략 표기가 아니라 그냥 없음."""
    b = nodes.fetch_one(fetch_item(flow=None, flow_skipped=False))["briefings"][0]
    assert b.flow is None and b.skipped == ("investor_flows",)


# ── summarize (F14 · M3) ─────────────────────────────────────────
#
# LLM은 **있으면 좋은 층**이다. 이 묶음의 절반은 "없어도 메일이 간다"를 증명하는 데 쓴다.

from typing import Any  # noqa: E402

from briefing import llm  # noqa: E402
from briefing.state import briefing_key  # noqa: E402


def brief(ticker: str = "079940", name: str = "가비아", **kw: object) -> Briefing:
    base: dict[str, object] = {
        "signal": SignalRow(d=date(2026, 8, 25), strategy="mtf", ticker=ticker, name=name,
                            evidence={}),
        "corp_code": "00506294",
        "level": "red",
        "disclosures": (
            Disclosure(rcept_dt=date(2026, 8, 22), report_nm="전환사채권발행결정",
                       rcept_no="1", flr_nm=name),
        ),
    }
    base.update(kw)
    return Briefing.from_signal(**base)  # type: ignore[arg-type]


def st(**kw: object) -> dict[str, object]:
    s = initial_state(date(2026, 8, 26))
    s.update(kw)  # type: ignore[typeddict-item]
    return dict(s)


def fake_reply(payload: dict[str, Any]) -> llm.Reply:
    return llm.Reply(payload=payload, usage=llm.Usage(input_tokens=5100, output_tokens=420))


def test_analyze_keeps_valid_lines_and_records_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    b = brief()
    said = {"items": [{"ticker": "079940", "reason": "08/22 전환사채 발행 결정"}]}
    monkeypatch.setattr(llm, "summarize", lambda items: fake_reply(said))
    out = nodes.analyze(cast("Any", st(briefings=[b])))
    assert out["summaries"] == {briefing_key("mtf", "079940"): "08/22 전환사채 발행 결정"}
    assert out["llm_tokens"] == 5520
    assert not out.get("summary_error")


def test_analyze_drops_only_the_line_that_breaks_a_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """금지어가 든 한 줄만 버린다 — 나머지 종목의 요약은 남는다 (N13)."""
    good, bad = brief(), brief("227950", "엔투텍")
    monkeypatch.setattr(
        llm, "summarize",
        lambda items: fake_reply({"items": [
            {"ticker": "079940", "reason": "08/22 전환사채 발행 결정"},
            {"ticker": "227950", "reason": "지금이 매수 시점이다"},
        ]}),
    )
    out = nodes.analyze(cast("Any", st(briefings=[good, bad])))
    assert list(out["summaries"]) == [briefing_key("mtf", "079940")]
    assert set(out["verdicts"]) == {"079940", "227950"}  # 판정은 둘 다 나간다


def test_analyze_swallows_a_missing_key_and_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 없어도 메일은 간다 (R12). 예외가 새면 그날 메일이 통째로 사라진다."""
    def boom(items: object) -> object:
        raise llm.LlmUnavailable("ANTHROPIC_API_KEY 없음")

    monkeypatch.setattr(llm, "summarize", boom)
    out = nodes.analyze(cast("Any", st(briefings=[brief()])))
    assert "ANTHROPIC_API_KEY" in out["summary_error"]
    assert out.get("summaries", {}) == {}


@pytest.mark.parametrize(
    "exc", [llm.LlmError("모델이 응답을 거부했다"), RuntimeError("생각지 못한 것")]
)
def test_analyze_never_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """`LlmError`든 아니든 예외는 밖으로 나가지 않는다 — `record_run`에 못 가면 기록이 사라진다."""
    def boom(items: object) -> object:
        raise exc

    monkeypatch.setattr(llm, "summarize", boom)
    out = nodes.analyze(cast("Any", st(briefings=[brief()])))
    assert out["summary_error"]


def test_analyze_does_not_call_the_model_when_there_is_nothing_to_analyze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공시를 못 본 종목뿐이면 부르지 않는다 — 돈이 든다."""
    called = []
    monkeypatch.setattr(llm, "summarize", lambda items: called.append(items))
    out = nodes.analyze(cast("Any", st(briefings=[brief(level="unknown", disclosures=())])))
    assert called == []
    assert out.get("summaries", {}) == {}
    assert "verdicts" in out  # 판정은 LLM과 무관하게 항상 나간다 (F18)


def test_analyze_skips_a_briefing_that_already_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """멱등 (N6) — 어제 만든 요약을 다시 사겠다고 LLM을 부르지 않는다."""
    called = []
    monkeypatch.setattr(llm, "summarize", lambda items: called.append(items))
    out = nodes.analyze(cast("Any", st(briefings=[brief(summary="이미 있다")])))
    assert called == []
    assert out.get("summaries", {}) == {}
    assert "verdicts" in out


# ── 요약이 본문·저장까지 흘러가는가 ──────────────────────────────


def test_summaries_reach_the_rendered_body() -> None:
    b = brief()
    key = briefing_key("mtf", "079940")
    out = nodes.render(cast("Any", st(briefings=[b], signals=[], summaries={key: "요약 한 줄"},
                                      data_date=date(2026, 8, 26))))
    assert "요약 한 줄" in out["html"]
    assert "요약 한 줄" in out["text"]


def test_summaries_reach_the_saved_row() -> None:
    """`ksb_briefings.summary`에 남아야 내일 다시 부르지 않는다 (N6)."""
    b = brief()
    key = briefing_key("mtf", "079940")
    rows = [x.to_row() for x in nodes._ordered(
        cast("Any", st(briefings=[b], signals=[], summaries={key: "요약 한 줄"}))
    )]
    assert rows[0]["summary"] == "요약 한 줄"


# ── publish — 전문 페이지 (F20 v2) ───────────────────────────────
#
# **있으면 좋은 층이다.** 배포가 실패해도 메일은 링크 없이 간다.

from briefing import deploy as _deploy  # noqa: E402


def test_publish_puts_the_url_in_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_deploy, "deploy", lambda day, html: f"https://x/{day}.html")
    out = nodes.publish(cast("Any", st(briefings=[brief()], data_date=date(2026, 8, 26))))
    assert out["page_url"] == "https://x/20260826.html"


def test_publish_swallows_a_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 없어도 메일은 간다 — 링크만 빠진다."""
    def boom(day: str, html: str) -> str:
        raise _deploy.DeployUnavailable("VERCEL_TOKEN 없음")

    monkeypatch.setattr(_deploy, "deploy", boom)
    out = nodes.publish(cast("Any", st(briefings=[brief()], data_date=date(2026, 8, 26))))
    assert "page_url" not in out and "VERCEL_TOKEN" in out["page_error"]


def test_publish_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(day: str, html: str) -> str:
        raise RuntimeError("생각지 못한 것")

    monkeypatch.setattr(_deploy, "deploy", boom)
    out = nodes.publish(cast("Any", st(briefings=[brief()], data_date=date(2026, 8, 26))))
    assert out["page_error"]


def test_publish_does_nothing_on_a_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    def record(day: str, html: str) -> str:
        called.append(day)
        return "x"

    monkeypatch.setattr(_deploy, "deploy", record)
    out = nodes.publish(
        cast("Any", st(briefings=[brief()], data_date=date(2026, 8, 26), dry_run=True))
    )
    assert called == [] and out == {}


def test_the_mail_carries_the_link_when_the_page_went_up() -> None:
    b = brief()
    out = nodes.render(
        cast(
            "Any",
            st(briefings=[b], signals=[], data_date=date(2026, 8, 26),
               page_url="https://x/20260826.html"),
        )
    )
    assert "https://x/20260826.html" in out["html"]


def test_the_mail_has_no_link_when_the_page_failed() -> None:
    """링크 없이도 메일은 성립한다 — 발췌는 그대로 있다."""
    b = brief(summary="분석 서술")
    out = nodes.render(
        cast("Any", st(briefings=[b], signals=[], data_date=date(2026, 8, 26), page_error="x"))
    )
    assert "자세히 보기" not in out["html"]
    assert "분석 서술" in out["html"]


def test_the_summed_overhang_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """본문이 여러 건이면 합계가 핵심이다 — 맞게 더한 값을 지어낸 것으로 보면 안 된다.

    2026-08-31 실호출: 엔투텍 18.63% + 5.41% = 24.04%가 버려졌다.
    """
    from briefing.models import EventBody

    b = brief(
        bodies=(
            EventBody(rcept_no="a", event_type="cb_issuance", overhang_pct=18.63),
            EventBody(rcept_no="b", event_type="cb_issuance", overhang_pct=5.41),
        )
    )
    assert nodes._overhang_values(b) == {18.63, 5.41, 24.04}


def test_a_single_body_has_no_sum_to_allow() -> None:
    from briefing.models import EventBody

    b = brief(bodies=(EventBody(rcept_no="a", event_type="cb_issuance", overhang_pct=5.10),))
    assert nodes._overhang_values(b) == {5.10}
