"""그래프 노드.

**노드는 얇다** (SPEC N11). 상태에서 값을 꺼내 도메인 함수를 부르고 결과를 상태에 담는 것까지가
노드의 일이다. 함수 하나가 20줄을 넘으면 로직이 새어 들어온 것이니 도메인 모듈로 옮긴다.

**I/O 노드는 예외를 밖으로 내지 않는다.** `fetch_one`·`summarize`·`send_email`은 실패를 상태에 적고,
실패 판정은 `finalize` 한 곳에서만 한다. 그래야 `record_run`에 반드시 도달한다.

M0 단계: 배선을 먼저 세운다. `TODO(M*)`가 붙은 노드는 통과 스텁이다.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import timedelta
from typing import Any

from langgraph.types import Send

from briefing import analysis as analysing
from briefing import corp, dart, enrich, llm, notify, store, verdict
from briefing import render as rendering
from briefing.models import WINDOW_DAYS, Briefing, RunRecord, SendResult
from briefing.state import (
    FAILING_STATUSES,
    GATE_MISSING,
    GATE_READY,
    GATE_STALE,
    GATE_WAIT_SECONDS,
    MAX_GATE_ATTEMPTS,
    STATUS_DART_FAILED,
    STATUS_DART_PARTIAL,
    STATUS_GATE_TIMEOUT,
    STATUS_NO_SIGNALS,
    STATUS_OK,
    STATUS_SEND_FAILED,
    BriefingState,
    FetchItem,
    briefing_key,
)
from briefing.verdict import Verdict


class BriefingRunError(RuntimeError):
    """배치가 실패했음을 알리는 예외. `finalize`에서만 올린다 (SPEC N5)."""


# ── 게이트 (F1) ─────────────────────────────────────────────────


def gate(state: BriefingState) -> dict[str, Any]:
    """오늘 `ksa_runs` 행을 읽어 신호가 저장됐는지 판정한다 (F1).

    이벤트(dispatch)는 "워크플로가 끝났다"만 말한다. "신호가 저장됐다"는 DB가 말한다.
    """
    run = store.fetch_today_run(store.conn(), state["run_date"])
    if run is None:
        print("[gate] ksa_runs 오늘 행 없음")
        return {"gate": GATE_MISSING, "data_date": None}
    data_date, status = run
    verdict = GATE_STALE if status == "stale_data" else GATE_READY
    print(f"[gate] 상위 status={status} data_date={data_date} → {verdict}")
    return {"gate": verdict, "data_date": data_date}


def route_gate(state: BriefingState) -> str:
    """게이트 판정으로 다음 노드를 고른다 — 판정이 그래프 위에 보인다.

    Returns:
        `ready` / `stale` / `missing`(재시도) / `timeout`(포기 → record_run).
    """
    g = state.get("gate", GATE_MISSING)
    if g == GATE_READY:
        return "ready"
    if g == GATE_STALE:
        return "stale"
    return "missing" if state.get("attempts", 0) < MAX_GATE_ATTEMPTS else "timeout"


def wait(state: BriefingState) -> dict[str, Any]:
    """상위 배치를 기다린다. 테스트는 이 노드를 반드시 스텁으로 덮는다."""
    n = state.get("attempts", 0) + 1
    print(f"[wait] ksa_runs 오늘 행 없음 — {GATE_WAIT_SECONDS}초 대기 ({n}/{MAX_GATE_ATTEMPTS})")
    time.sleep(GATE_WAIT_SECONDS)
    return {"attempts": n}


# ── 입력 (F2·F3) ────────────────────────────────────────────────


def load_signals(state: BriefingState) -> dict[str, Any]:
    """그날 메일에 실린 신호(`suppressed = false`)와 기존 브리핑을 읽는다 (F2·N6)."""
    d = state.get("data_date") or state["run_date"]
    c = store.conn()
    signals = store.fetch_signals(c, d)
    existing = store.fetch_briefings(c, d)
    print(f"[load_signals] {d} 신호 {len(signals)}건 · 기존 브리핑 {len(existing)}건")
    return {"signals": signals, "existing": existing}


def load_corps(state: BriefingState) -> dict[str, Any]:
    """`corpCode.xml` 1회 → {ticker: corp_code} (F3). 실패하면 전 종목이 `unknown`이 된다."""
    if not state.get("signals"):
        return {"corp_codes": {}}
    try:
        codes = corp.parse_corp_codes(dart.fetch_corp_codes())
    except (dart.DartError, corp.CorpCodeError) as exc:
        print(f"[load_corps] 실패 → 전 종목 코드 미확인: {exc}")
        return {"corp_codes": {}}
    print(f"[load_corps] 상장사 {len(codes):,}개")
    return {"corp_codes": codes}


def load_market(state: BriefingState) -> dict[str, Any]:
    """신호 종목의 시세 참고를 상위 DB에서 **SQL 한 번**으로 읽는다 (F12·D14 v2).

    외부 호출도 새 키도 없다 — 상위 `krx-stock-charts`가 매일 `ksc_tickers.mktcap`을 채우고
    (상위 F8), 거래대금은 `ksc_bars.a`에 이미 있다. 실패해도 raise하지 않는다 — 참고 층이다.
    """
    tickers = sorted({s.ticker for s in state.get("signals", [])})
    try:
        flows = store.fetch_flows(store.conn(), tickers)
    except Exception as exc:  # noqa: BLE001 — 참고 층이 메일을 막지 않는다
        print(f"[load_market] 시세 조회 실패 → 생략: {exc}")
        return {"flows": {}, "flow_skipped": f"시세 조회 실패: {exc}"}
    print(f"[load_market] 시세 참고 {len(flows)}/{len(tickers)}종목")
    return {"flows": flows, "flow_skipped": "" if flows or not tickers else "상위 시총 데이터 없음"}


def fan_out(state: BriefingState) -> list[Send] | str:
    """종목마다 `fetch_one`을 띄운다. 신호가 없으면 `summarize`로 직행한다.

    빈 Send 목록을 돌려주면 그래프가 거기서 **조용히 끝난다** — 그래서 문자열 경로를 둔다.
    """
    signals = state.get("signals", [])
    if not signals:
        return "analyze"
    corps, existing = state.get("corp_codes", {}), state.get("existing", {})
    flows, flow_skipped = state.get("flows", {}), bool(state.get("flow_skipped"))
    return [
        Send(
            "fetch_one",
            FetchItem(
                signal=s,
                corp_code=corps.get(s.ticker),
                existing=existing.get(briefing_key(s.strategy, s.ticker)),
                force=state["force"],
                run_date=state["run_date"],
                flow=flows.get(s.ticker),
                flow_skipped=flow_skipped,
            ),
        )
        for s in signals
    ]


def fetch_one(item: FetchItem) -> dict[str, Any]:
    """종목 하나 — ① 공시(MCP→REST 폴백) → ② 판정 → ③ 보조 신호(실패 시 생략) → Briefing.

    **실패해도 raise하지 않는다.** 그날 브리핑이 이미 있으면(`existing`) 다시 부르지 않는다 (N6).
    corp_code가 없으면 `unknown`, 공시를 어느 경로로도 못 받으면 `error` —
    한 종목이 fan-out을 죽이지 않는다. 호출 순서·폴백·생략은 `enrich.py`에 있다 (N11).
    """
    s, code, end = item["signal"], item["corp_code"], item["run_date"]
    if item["existing"] is not None and not item["force"]:
        return {"briefings": [item["existing"]], "dart_calls": 0}
    if code is None:
        return {"briefings": [Briefing.from_signal(s, None, "unknown")], "dart_calls": 0}
    try:
        b = enrich.briefing_for(
            s,
            code,
            end - timedelta(days=WINDOW_DAYS),
            end,
            flow=item.get("flow"),
            flow_skipped=item.get("flow_skipped", False),
        )
    except dart.DartError as exc:
        print(f"[fetch_one] {s.name} [{s.ticker}] 공시 조회 실패(MCP·REST): {exc}")
        b = Briefing.from_signal(s, code, "error", error=str(exc))
    return {"briefings": [b], "dart_calls": 1}


# ── 판정 · 근거 서술 · 본문 (F18 · F19 · F7·F8) ─────────────────


def analyze(state: BriefingState) -> dict[str, Any]:
    """판정(코드) → Claude 근거 서술 1회 일괄 (F18·F19). **예외를 밖으로 내지 않는다.**

    두 층이 겹쳐 있다:

    1. **`verdict.judge()`가 판정과 점수를 낸다** — 순수 함수다. LLM이 죽어도 이건 나간다.
    2. LLM은 그 판정을 **설명**한다. 실패하면 서술만 빠지고 판정·점수·공시·뉴스·수급은 그대로다.

    LLM은 있으면 좋은 층이다 (R12). 여기서 예외가 새면 `record_run`에 못 가
    그날 실행 기록까지 사라진다.
    """
    briefings = state.get("briefings", [])
    verdicts = {b.ticker: verdict.judge(b) for b in briefings}
    todo = [b for b in briefings if not b.summary]
    items = analysing.build_input(todo, verdicts)
    if not items:
        return {"verdicts": verdicts}
    try:
        reply = llm.summarize(items)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패도 판정·메일을 막지 않는다
        print(f"[analyze] 근거 서술 생략: {exc}")
        return {"verdicts": verdicts, "summary_error": str(exc)}
    kept, dropped = _validated(reply, items, todo, verdicts)
    for why in dropped:
        print(f"[analyze] 버림 — {why}")
    out = {briefing_key(b.strategy, b.ticker): kept[b.ticker] for b in todo if b.ticker in kept}
    print(f"[analyze] {len(out)}/{len(items)}종목 · 토큰 {reply.usage.total:,}")
    return {"verdicts": verdicts, "summaries": out, "llm_tokens": reply.usage.total}


def _validated(
    reply: llm.Reply,
    items: list[dict[str, Any]],
    todo: list[Briefing],
    verdicts: dict[str, Verdict],
) -> tuple[dict[str, str], list[str]]:
    """응답 검증 인자를 모은다 — 노드가 20줄을 넘지 않게 (N3)."""
    return analysing.validate(
        reply.payload,
        [i["ticker"] for i in items],
        stands={t: v.stand for t, v in verdicts.items()},
        risk_counts={b.ticker: len(b.flags) for b in todo},
        overhangs={
            b.ticker: {x.overhang_pct for x in b.bodies if x.overhang_pct is not None}
            for b in todo
        },
    )


def render(state: BriefingState) -> dict[str, Any]:
    """제목·평문·HTML을 만든다 (F7·F8). 순수 함수를 부를 뿐이다."""
    briefings = _ordered(state)
    d = state.get("data_date") or state["run_date"]
    stale = state.get("gate") == GATE_STALE
    err = state.get("summary_error", "")
    return {
        "subject": rendering.subject(briefings, d, stale=stale),
        "text": rendering.text(briefings, d, stale=stale, summary_error=err),
        "html": rendering.html(
            briefings,
            d,
            verdicts=state.get("verdicts", {}),
            page_url=state.get("page_url", ""),
            stale=stale,
            summary_error=err,
        ),
    }


# ── 저장 · 발송 · 기록 (F9 · F10) ───────────────────────────────


def persist(state: BriefingState) -> dict[str, Any]:
    """`ksb_briefings` upsert (F9). dry-run이면 건너뛴다. 실패해도 발송은 시도한다."""
    briefings = _ordered(state)
    if state.get("dry_run") or not briefings:
        return {}
    try:
        n = store.upsert_briefings(store.rest_client(), briefings)
        print(f"[persist] {n}건 저장")
    except Exception as exc:  # noqa: BLE001 — 저장 실패가 메일을 막지 않는다
        print(f"[persist] 저장 실패(무시): {exc}")
    return {}


def send_email(state: BriefingState) -> dict[str, Any]:
    """Gmail SMTP 발송 (F10). **예외를 밖으로 내지 않고** `SendResult`를 적는다."""
    if state.get("dry_run"):
        print(f"[send_email] dry-run — 보내지 않음. 제목: {state.get('subject', '')}")
        return {"send": SendResult(ok=True, sent_n=0)}
    try:
        n = notify.send(state["subject"], state["text"], state["html"])
        print(f"[send_email] {n}명에게 발송")
        return {"send": SendResult(ok=True, sent_n=n)}
    except Exception as exc:  # noqa: BLE001 — 실패 판정은 finalize 한 곳에서
        print(f"[send_email] 발송 실패: {exc}")
        return {"send": SendResult(ok=False, error=f"{type(exc).__name__}: {exc}")}


def _ordered(state: BriefingState) -> list[Briefing]:
    """상위 메일과 같은 순서로 (전략·티커) + **요약을 붙인다**.

    fan-out은 완료 순서로 합쳐지므로 여기서 순서를 되돌린다.
    요약을 여기 한 곳에서 붙여야 본문(`render`)과 저장(`persist`)이 같은 값을 본다 —
    한쪽만 붙이면 메일에는 요약이 있는데 DB에는 없어 내일 또 LLM을 부른다.
    """
    order = {(s.strategy, s.ticker): i for i, s in enumerate(state.get("signals", []))}
    summaries = state.get("summaries", {})
    out: list[Briefing] = []
    for b in sorted(
        state.get("briefings", []), key=lambda b: order.get((b.strategy, b.ticker), 10**6)
    ):
        text = summaries.get(briefing_key(b.strategy, b.ticker))
        out.append(dataclasses.replace(b, summary=text) if text else b)
    return out


def _status_of(state: BriefingState) -> str:
    """상태로 `ksb_runs.status`를 정한다. 심각한 것부터 본다."""
    if state.get("gate", GATE_MISSING) == GATE_MISSING:
        return STATUS_GATE_TIMEOUT
    send = state.get("send")
    if send is not None and not send.ok:
        return STATUS_SEND_FAILED
    briefings = state.get("briefings", [])
    errors = sum(1 for b in briefings if b.level == "error")
    if briefings and errors == len(briefings):
        return STATUS_DART_FAILED
    if errors:
        return STATUS_DART_PARTIAL
    return STATUS_NO_SIGNALS if not state.get("signals") else STATUS_OK


def record_run(state: BriefingState) -> dict[str, Any]:
    """실행 결과를 `ksb_runs`에 남기고 최종 상태를 정한다. 실패해도 **기록이 먼저**다."""
    status = _status_of(state)
    briefings = state.get("briefings", [])
    send = state.get("send")
    detail = enrich.run_detail(briefings)
    if send is not None:
        detail["send"] = {"ok": send.ok, "sent_n": send.sent_n, "error": send.error}
    if err := state.get("summary_error", ""):
        detail["summary_error"] = err
    if skipped := state.get("flow_skipped", ""):
        detail["flow_skipped"] = skipped
    record = RunRecord(
        data_date=state.get("data_date"),
        status=status,  # type: ignore[arg-type]
        signal_n=len(state.get("signals", [])),
        red_n=sum(1 for b in briefings if b.level == "red"),
        amber_n=sum(1 for b in briefings if b.level == "amber"),
        error_n=sum(1 for b in briefings if b.level == "error"),
        dart_calls=state.get("dart_calls", 0),
        summary_n=len(state.get("summaries", {})),
        llm_tokens=state.get("llm_tokens", 0),
        detail=detail,
    )
    if not state.get("dry_run"):
        try:
            store.insert_run(store.rest_client(), record)
        except Exception as exc:  # noqa: BLE001 — 기록 실패가 알림을 삼키면 안 된다
            print(f"[record_run] 기록 실패(무시): {exc}")
    print(f"[record_run] status={status} signals={record.signal_n} red={record.red_n}")
    return {"status": status}


def finalize(state: BriefingState) -> dict[str, Any]:
    """실패 상태면 예외를 올린다 (SPEC N5). **실패 판정 지점은 여기 하나뿐이다.**

    Raises:
        BriefingRunError: 게이트 타임아웃 · DART 실패 · 발송 실패.
    """
    status = state.get("status", STATUS_OK)
    if status in FAILING_STATUSES:
        raise BriefingRunError(f"브리핑 실패 ({status})")
    return {}
