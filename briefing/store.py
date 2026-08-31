"""Supabase 읽기·쓰기.

| 경로 | 쓰는 곳 | 이유 |
|------|---------|------|
| psycopg (직접 SQL) | `ksa_*`·`ksc_*` 읽기 | 1,000행 절단 없음 · 집계가 SQL에서 끝남 |
| supabase-py (REST) | `ksb_*` 쓰기 | 소량이고 upsert가 간단하다 |

`ksa_*`·`ksc_*`에는 절대 쓰지 않는다 — 상위 프로젝트 소유다. 읽기만 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg
from supabase import Client, create_client

from briefing import config
from briefing.models import (
    Anomaly,
    Briefing,
    Disclosure,
    Flag,
    Flow,
    FlowDay,
    Insider,
    InvestorFlows,
    NewsItem,
    RunRecord,
    SignalRow,
)

_conn: psycopg.Connection[Any] | None = None


def rest_client() -> Client:
    """service_role 클라이언트 — RLS를 우회한다. `ksb_*` 쓰기에만 쓴다."""
    return create_client(config.require("SUPABASE_URL"), config.require("SUPABASE_SERVICE_KEY"))


def conn() -> psycopg.Connection[Any]:
    """배치용 공유 연결. 노드마다 새로 붙지 않는다 — `close()`로 닫는다.

    Note:
        URL은 트랜잭션 풀러(6543)다. 프리페어드 스테이트먼트를 재사용하지 못하므로
        `prepare_threshold=None`으로 끈다 (상위 프로젝트와 동일).
    """
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(config.require("SUPABASE_DATABASE_URL"), prepare_threshold=None)
    return _conn


def close() -> None:
    """공유 연결을 닫는다. `main`이 끝낼 때 부른다."""
    global _conn
    if _conn is not None and not _conn.closed:
        _conn.close()
    _conn = None


# ── ksa_runs (읽기만) ────────────────────────────────────────────


def fetch_today_run(c: psycopg.Connection[Any], run_date: date) -> tuple[date | None, str] | None:
    """오늘(KST) 상위 배치의 마지막 실행 기록 — 게이트 판정 근거 (F1).

    Args:
        c: DB 연결.
        run_date: 실행 기준일 (KST 날짜).

    Returns:
        `(data_date, status)`. 그날 행이 없으면 None. `data_date`는 상위가 조회에
        실패한 날 null일 수 있다(`stale_data`).

    Note:
        상위는 저장 후 발송하므로 `send_failed`여도 신호는 있다. 상태 해석은 노드가 한다.
    """
    row = c.execute(
        "select data_date, status from ksa_runs"
        " where (run_at at time zone 'Asia/Seoul')::date = %s"
        " order by run_at desc limit 1",
        (run_date,),
    ).fetchone()
    return (row[0], str(row[1])) if row else None


def fetch_signal_tickers_since(c: psycopg.Connection[Any], since: date) -> list[tuple[str, str]]:
    """일정 기간의 신호 종목(억제 제외) — 표본 수집·드라이런용.

    Args:
        c: DB 연결.
        since: 이 날짜 이후의 신호.

    Returns:
        `(ticker, name)` 중복 없이, 티커 순.
    """
    rows = c.execute(
        "select distinct ticker, name from ksa_signals"
        " where d >= %s and not suppressed order by ticker",
        (since,),
    ).fetchall()
    return [(str(t), str(n)) for t, n in rows]


def fetch_signal_rows_since(c: psycopg.Connection[Any], since: date) -> list[SignalRow]:
    """일정 기간의 신호 행(억제 제외) — 드라이런용. `evidence`는 싣지 않는다.

    Returns:
        `(d, ticker)` 순. 같은 종목이 여러 날·여러 전략에 나올 수 있다.
    """
    rows = c.execute(
        "select d, strategy, ticker, name from ksa_signals"
        " where d >= %s and not suppressed order by d, ticker",
        (since,),
    ).fetchall()
    return [SignalRow(d=d, strategy=str(s), ticker=str(t), name=str(n)) for d, s, t, n in rows]


FLOW_WINDOW_DAYS = 30  # 수급을 볼 거래일 수 (F17)


def _foreign_total(foreign: int | None, foreign_etc: int | None) -> int | None:
    """외국인합계 = 외국인 + 기타외국인.

    상위는 둘을 따로 담는다 — pykrx의 `get_market_net_purchases_of_equities_by_ticker`가
    `외국인합계`를 인자로 받지 않기 때문이다 (상위 2026-08-30 실측).
    **둘 다 없으면 None이다** — 0으로 채우면 "거래가 없었다"가 "값이 없다"를 덮는다.
    """
    got = [v for v in (foreign, foreign_etc) if v is not None]
    return sum(got) if got else None


def fetch_flows_30d(
    c: psycopg.Connection[Any],
    tickers: Sequence[str],
    days: int = FLOW_WINDOW_DAYS,
) -> dict[str, InvestorFlows]:
    """기관·외국인·개인 순매수 최근 N거래일 (F17·D22).

    **호출 0회, 키 0개.** 상위 `krx-stock-charts`가 매일 채운 `ksc_investor_flows`를
    SQL 한 번으로 읽는다 (상위 SPEC F14, 2026-08-30 신설 — 시총 F8과 같은 방식).

    종목마다 마지막 N거래일을 따로 센다. 어떤 종목은 거래정지로 행이 적을 수 있는데,
    날짜로 자르면 그런 종목의 창이 조용히 짧아진다.

    Args:
        c: DB 연결.
        tickers: 대상 종목.
        days: 종목당 거래일 수.

    Returns:
        `{ticker: InvestorFlows}` — 날짜 오름차순. **행이 없는 종목은 빠진다**
        (호출자가 `⚠ 수급 생략`으로 표기한다, D15).
    """
    if not tickers:
        return {}
    rows = c.execute(
        """
        select f.ticker, f.d, f.inst_net, f.foreign_net, f.foreign_etc_net, f.indiv_net
          from ksc_investor_flows f
          join lateral (
              select d from ksc_investor_flows
               where ticker = f.ticker
               order by d desc limit %s
          ) w on w.d = f.d
         where f.ticker = any(%s)
         order by f.ticker, f.d
        """,
        (days, list(tickers)),
    ).fetchall()
    out: dict[str, list[FlowDay]] = {}
    for ticker, d, inst, foreign, foreign_etc, indiv in rows:
        out.setdefault(str(ticker), []).append(
            FlowDay(
                d=d,
                inst=None if inst is None else int(inst),
                foreign=_foreign_total(foreign, foreign_etc),
                indiv=None if indiv is None else int(indiv),
            )
        )
    return {t: InvestorFlows(days=tuple(v)) for t, v in out.items()}


def fetch_flows(
    c: psycopg.Connection[Any], tickers: Sequence[str], days: int = 5
) -> dict[str, Flow]:
    """시세 참고 — 시총·상장주식수는 `ksc_tickers`, 최근 N거래일 거래대금은 `ksc_bars` (F12·D14 v2).

    **호출 0회, 키 0개.** 상위 `krx-stock-charts`가 매일 채워 둔 값을 SQL 한 번으로 읽는다
    (상위 SPEC F8, 2026-08-29 신설 — korea-stock-mcp + KRX OPEN API 키를 대체했다).

    Args:
        c: DB 연결.
        tickers: 대상 종목.
        days: 거래대금을 합칠 최근 거래일 수.

    Returns:
        `{ticker: Flow}`. 시총이 아직 없는 종목(상위 수집 전)은 빠진다.
    """
    if not tickers:
        return {}
    rows = c.execute(
        """
        select t.ticker, t.mktcap, t.list_shrs, t.mktcap_d,
               coalesce(x.trdval, 0), coalesce(x.days, 0), x.last_d, coalesce(x.close, 0)
          from ksc_tickers t
          left join lateral (
              select sum(b.a) as trdval, count(*) as days,
                     max(b.d) as last_d, (array_agg(b.c order by b.d desc))[1] as close
                from (select d, a, c from ksc_bars
                       where ticker = t.ticker and timeframe = 'D'
                       order by d desc limit %s) b
          ) x on true
         where t.ticker = any(%s) and t.mktcap is not null
        """,
        (days, list(tickers)),
    ).fetchall()
    return {
        str(ticker): Flow(
            bas_dd=(last_d or mktcap_d).strftime("%Y%m%d"),
            close=int(close),
            mktcap=int(mktcap),
            list_shrs=int(list_shrs or 0),
            trdval_5d=int(trdval),
            days=int(n_days),
        )
        for ticker, mktcap, list_shrs, mktcap_d, trdval, n_days, last_d, close in rows
    }


def fetch_signals(c: psycopg.Connection[Any], d: date) -> list[SignalRow]:
    """그날 메일에 실린 신호 (F2).

    `sent_email`은 상위가 저장하지 않는다 — 메일 집합은 `suppressed = false` 전체다
    (2026-08-26 실측, SPEC F2). 순서는 상위 메일과 같게 전략·티커 순.
    """
    rows = c.execute(
        "select d, strategy, ticker, name, evidence from ksa_signals"
        " where d = %s and not suppressed order by strategy, ticker",
        (d,),
    ).fetchall()
    return [
        SignalRow(d=dd, strategy=str(st), ticker=str(t), name=str(n), evidence=ev or {})
        for dd, st, t, n, ev in rows
    ]


# ── ksb_briefings ───────────────────────────────────────────────


def _anomaly_of(raw: dict[str, Any] | None) -> Anomaly | None:
    """`ksb_briefings.anomaly` jsonb → 모델. 예전 행에는 null이 들어 있다."""
    if not raw:
        return None
    return Anomaly(
        score=int(raw.get("score", 0)),
        verdict=str(raw.get("verdict", "")),
        summary=str(raw.get("summary", "")),
        flags=tuple(raw.get("flags") or ()),
    )


def _insider_of(raw: dict[str, Any] | None) -> Insider | None:
    if not raw:
        return None
    return Insider(
        signal=str(raw.get("signal", "")),
        buy_events=int(raw.get("buy_events", 0)),
        sell_events=int(raw.get("sell_events", 0)),
        unique_buyers=int(raw.get("unique_buyers", 0)),
        unique_sellers=int(raw.get("unique_sellers", 0)),
        net_change_shares=int(raw.get("net_change_shares", 0)),
        summary=str(raw.get("summary", "")),
    )


def _flow_of(raw: dict[str, Any] | None) -> Flow | None:
    if not raw:
        return None
    return Flow(
        bas_dd=str(raw.get("bas_dd", "")),
        close=int(raw.get("close", 0)),
        mktcap=int(raw.get("mktcap", 0)),
        list_shrs=int(raw.get("list_shrs", 0)),
        trdval_5d=int(raw.get("trdval_5d", 0)),
        days=int(raw.get("days", 0)),
    )


def _news_of(raw: list[dict[str, Any]] | None) -> tuple[NewsItem, ...]:
    return tuple(
        NewsItem(
            title=str(n.get("title", "")),
            link=str(n.get("link", "")),
            origin=str(n.get("origin", "")),
            published=date.fromisoformat(n["published"]) if n.get("published") else None,
        )
        for n in raw or ()
    )


def fetch_briefings(c: psycopg.Connection[Any], d: date) -> dict[str, Briefing]:
    """그날 이미 있는 브리핑 — 멱등 판단용 (N6). 키는 `briefing_key`와 같은 형식.

    **`to_row()`가 쓰는 열을 전부 되살린다.** 예전에는 공시 목록까지만 복원했는데,
    재실행에서 `fetch_one`이 그 반쪽 브리핑을 돌려주고 `persist`가 그대로 덮어써
    **뉴스·anomaly·flow가 지워졌다** (2026-08-30, 15종목 실제 소실).
    되살리는 열이 저장하는 열보다 적으면 재실행이 그 차이만큼 지운다 —
    `tests/test_store.py`의 왕복 테스트가 이 계약을 잠근다. 열을 늘릴 때 여기도 함께 늘린다.

    `conditions`·`close`·`change_pct`는 열이 아니다 — 상위 `evidence`에서 매번 새로 온다.
    """
    rows = c.execute(
        "select d, strategy, ticker, name, corp_code, level, flags, disclosures,"
        " window_days, summary, anomaly, insider, flow, news"
        " from ksb_briefings where d = %s",
        (d,),
    ).fetchall()
    out: dict[str, Briefing] = {}
    for (
        dd, st, t, name, code, level, flags, discs, window, summ,
        anomaly, insider, flow, news,
    ) in rows:
        out[f"{st}:{t}"] = Briefing(
            d=dd,
            strategy=str(st),
            ticker=str(t),
            name=str(name),
            corp_code=code,
            level=level,
            flags=tuple(
                Flag(
                    rule=f["rule"],
                    level=f["level"],
                    rcept_no=f["rcept_no"],
                    report_nm=f["report_nm"],
                )
                for f in flags or []
            ),
            disclosures=tuple(
                Disclosure(
                    rcept_dt=date.fromisoformat(x["rcept_dt"]),
                    report_nm=x["report_nm"],
                    rcept_no=x["rcept_no"],
                    flr_nm=x.get("flr_nm", ""),
                    corrected=bool(x.get("corrected", False)),
                )
                for x in discs or []
            ),
            window_days=int(window),
            summary=summ,
            anomaly=_anomaly_of(anomaly),
            insider=_insider_of(insider),
            flow=_flow_of(flow),
            news=_news_of(news),
        )
    return out


# 한 문장에 담는 최대 행 수. 한 행이 크다 — 공시 목록 + 뉴스 5건 + 근거 서술 2,000자.
# 44건을 한 번에 보냈더니 Supabase가 statement timeout(57014)으로 끊었고,
# 메일·전문 페이지는 나갔는데 DB에는 아무것도 안 남았다 (2026-08-31 실측).
# 15건까지는 통과하던 값이라 그 아래로 잡는다.
BRIEFING_UPSERT_CHUNK = 10


def upsert_briefings(client: Client, briefings: Sequence[Briefing]) -> int:
    """브리핑을 저장한다 (F9). PK 기준 upsert라 재실행해도 같은 결과다 (N6).

    `BRIEFING_UPSERT_CHUNK`씩 나눠 보낸다. 나눠도 멱등은 그대로다 —
    PK가 같으면 덮어쓰므로 중간에 끊겨도 앞부분은 남는다.
    """
    rows = [b.to_row() for b in briefings]
    for i in range(0, len(rows), BRIEFING_UPSERT_CHUNK):
        client.table("ksb_briefings").upsert(rows[i : i + BRIEFING_UPSERT_CHUNK]).execute()
    return len(rows)


# ── ksb_runs ────────────────────────────────────────────────────


def insert_run(client: Client, record: RunRecord) -> None:
    """실행 기록을 남긴다. 실패해도 이것부터 쓴다 — 사후에 원인을 보는 유일한 기록이다."""
    client.table("ksb_runs").insert(record.to_row()).execute()


def briefed_today(c: psycopg.Connection[Any], run_date: date) -> bool:
    """오늘(KST) 이미 브리핑이 돌았는가 — 예비 cron의 no-op 판정 (F0 · `--if-not-briefed`).

    Args:
        c: DB 연결.
        run_date: 실행 기준일 (KST 날짜).

    Returns:
        `ksb_runs`에 그날 행이 하나라도 있으면 True. 상태는 보지 않는다 —
        실패로 끝난 날도 "돌았다"이며, 다시 돌리려면 `--force`로 수동 실행한다.
    """
    row = c.execute(
        "select exists(select 1 from ksb_runs where (run_at at time zone 'Asia/Seoul')::date = %s)",
        (run_date,),
    ).fetchone()
    return bool(row[0]) if row else False
