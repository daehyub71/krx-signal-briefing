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
