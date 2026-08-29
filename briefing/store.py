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

from briefing import config
from briefing.models import Flow, SignalRow

_conn: psycopg.Connection[Any] | None = None


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


# ── ksb_runs ────────────────────────────────────────────────────


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
