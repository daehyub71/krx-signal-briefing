"""store — SQL 문장의 형태. 실DB에 붙지 않는다 (커서 스텁)."""

from __future__ import annotations

from datetime import date
from typing import Any

from briefing import store


class FakeConn:
    """execute()가 받은 SQL·파라미터를 기록하고 정해진 행을 돌려준다."""

    def __init__(self, rows: list[tuple[Any, ...]]):
        self.rows = rows
        self.sql = ""
        self.params: tuple[Any, ...] = ()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeConn:
        self.sql, self.params = sql, params
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.rows)


def test_briefed_today_true_when_row_exists() -> None:
    c = FakeConn([(True,)])
    assert store.briefed_today(c, date(2026, 8, 26)) is True  # type: ignore[arg-type]
    assert "ksb_runs" in c.sql and "Asia/Seoul" in c.sql
    assert c.params == (date(2026, 8, 26),)


def test_briefed_today_false_when_absent() -> None:
    c = FakeConn([(False,)])
    assert store.briefed_today(c, date(2026, 8, 26)) is False  # type: ignore[arg-type]


def test_briefed_today_false_when_no_row() -> None:
    c = FakeConn([])
    assert store.briefed_today(c, date(2026, 8, 26)) is False  # type: ignore[arg-type]


def test_fetch_today_run_returns_data_date_and_status() -> None:
    c = FakeConn([(date(2026, 8, 25), "ok")])
    assert store.fetch_today_run(c, date(2026, 8, 26)) == (date(2026, 8, 25), "ok")  # type: ignore[arg-type]
    assert "ksa_runs" in c.sql and "Asia/Seoul" in c.sql and "desc" in c.sql.lower()
    assert c.params == (date(2026, 8, 26),)


def test_fetch_today_run_none_when_absent() -> None:
    assert store.fetch_today_run(FakeConn([]), date(2026, 8, 26)) is None  # type: ignore[arg-type]


def test_fetch_signal_tickers_since_returns_distinct_pairs() -> None:
    c = FakeConn([("079940", "가비아"), ("222040", "코스맥스엔비티")])
    out = store.fetch_signal_tickers_since(c, date(2026, 6, 1))  # type: ignore[arg-type]
    assert out == [("079940", "가비아"), ("222040", "코스맥스엔비티")]
    assert "ksa_signals" in c.sql and "distinct" in c.sql.lower() and "suppressed" in c.sql
    assert c.params == (date(2026, 6, 1),)


def test_fetch_signal_rows_since_builds_signal_rows() -> None:
    c = FakeConn([(date(2026, 8, 25), "mtf", "079940", "가비아")])
    out = store.fetch_signal_rows_since(c, date(2026, 6, 1))  # type: ignore[arg-type]
    assert len(out) == 1 and out[0].ticker == "079940" and out[0].strategy == "mtf"
    assert out[0].evidence == {} and "not suppressed" in c.sql


def test_fetch_flows_reads_upstream_tables() -> None:
    c = FakeConn(
        [
            (
                "079940",
                611_312_156_200,
                13_420_684,
                date(2026, 8, 27),
                3_250_819_650,
                5,
                date(2026, 8, 27),
                45550,
            )
        ]
    )
    flows = store.fetch_flows(c, ["079940"])  # type: ignore[arg-type]
    assert flows["079940"].mktcap == 611_312_156_200 and flows["079940"].days == 5
    assert flows["079940"].bas_dd == "20260827" and flows["079940"].close == 45550
    assert "ksc_tickers" in c.sql and "ksc_bars" in c.sql and "mktcap is not null" in c.sql
    assert c.params == (5, ["079940"])


def test_fetch_flows_empty_tickers_makes_no_query() -> None:
    c = FakeConn([])
    assert store.fetch_flows(c, []) == {}  # type: ignore[arg-type]
    assert c.sql == ""
