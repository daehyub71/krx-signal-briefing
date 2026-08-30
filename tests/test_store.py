"""store — SQL 문장의 형태. 실DB에 붙지 않는다 (커서 스텁)."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from briefing import store
from briefing.models import (
    Anomaly,
    Briefing,
    Disclosure,
    Flag,
    Flow,
    Insider,
    NewsItem,
)


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


# ── 재실행이 데이터를 지우지 않는다 (2026-08-30 실장애) ──────────
#
# `fetch_briefings`가 되살리는 열이 `to_row()`가 쓰는 열보다 적었다.
# 멱등 재실행에서 `fetch_one`이 그 반쪽 브리핑을 그대로 돌려주고 `persist`가 덮어써
# **15종목의 뉴스·anomaly·flow가 실제로 지워졌다.** 되살리는 열을 늘리고 왕복을 잠근다.


def full_briefing() -> Briefing:
    """모든 열이 채워진 브리핑 — 왕복에서 하나라도 빠지면 잡힌다."""
    return Briefing(
        d=date(2026, 8, 26),
        strategy="mtf",
        ticker="413630",
        name="씨피시스템",
        corp_code="01601222",
        level="red",
        flags=(
            Flag(
                rule="cb",
                level="red",
                rcept_no="20260826000286",
                report_nm="주요사항보고서(전환사채권발행결정)",
            ),
        ),
        disclosures=(
            Disclosure(
                rcept_dt=date(2026, 8, 26),
                report_nm="주요사항보고서(전환사채권발행결정)",
                rcept_no="20260826000286",
                flr_nm="씨피시스템",
                corrected=True,
            ),
        ),
        window_days=30,
        summary="08/26 전환사채 발행 결정",
        anomaly=Anomaly(score=25, verdict="watch", summary="정정 19.8%", flags=("x",)),
        insider=Insider(
            signal="sell_cluster", sell_events=5, unique_sellers=3, net_change_shares=-100
        ),
        flow=Flow(
            bas_dd="20260827",
            close=4000,
            mktcap=145_746_420_000,
            list_shrs=36_436_605,
            trdval_5d=81_039_010_488,
            days=5,
        ),
        news=(
            NewsItem(
                title="씨피시스템, 100억 규모 CB 발행",
                link="https://n.news.naver.com/x",
                origin="https://www.newsis.com/y",
                published=date(2026, 8, 26),
            ),
        ),
    )


class RowCursor:
    """`to_row()`가 만든 행을 DB 응답 모양으로 돌려주는 대역."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.columns: list[str] = []

    def execute(self, sql: str, params: Any = None) -> RowCursor:
        # select 절의 열 이름을 그대로 뽑아 그 순서로 값을 돌려준다 — 실제 DB와 같은 계약.
        head = sql.split("from")[0].removeprefix("select").strip()
        self.columns = [c.strip() for c in head.split(",")]
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        out: list[tuple[Any, ...]] = []
        for row in self.rows:
            values = []
            for col in self.columns:
                v = row[col]
                values.append(date.fromisoformat(v) if col == "d" else v)
            out.append(tuple(values))
        return out


def test_fetch_briefings_restores_every_column_that_persist_writes() -> None:
    """되살리는 열이 저장하는 열보다 적으면, 재실행이 그 차이만큼 지운다."""
    row = full_briefing().to_row()
    got = store.fetch_briefings(cast("Any", RowCursor([row])), date(2026, 8, 26))
    restored = got["mtf:413630"].to_row()
    missing = [k for k, v in row.items() if v is not None and restored[k] is None]
    assert not missing, f"재실행이 지우는 열: {missing}"


def test_fetch_briefings_round_trips_the_side_signals() -> None:
    row = full_briefing().to_row()
    b = store.fetch_briefings(cast("Any", RowCursor([row])), date(2026, 8, 26))["mtf:413630"]
    assert b.anomaly is not None and b.anomaly.score == 25
    assert b.insider is not None and b.insider.sell_events == 5
    assert b.flow is not None and b.flow.mktcap == 145_746_420_000
    assert len(b.news) == 1 and b.news[0].published == date(2026, 8, 26)
    assert b.news[0].title.startswith("씨피시스템")


def test_fetch_briefings_tolerates_rows_written_before_those_columns_existed() -> None:
    """예전 행에는 anomaly·flow·news가 null이다 — 그것 때문에 죽으면 안 된다."""
    row = full_briefing().to_row()
    row.update({"anomaly": None, "insider": None, "flow": None, "news": None, "summary": None})
    b = store.fetch_briefings(cast("Any", RowCursor([row])), date(2026, 8, 26))["mtf:413630"]
    assert b.anomaly is None and b.flow is None and b.news == () and b.summary is None
