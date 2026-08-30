"""models — 도메인 모델과 DB 행 변환 (ksb_briefings · ksb_runs 계약)."""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from briefing.models import (
    LEVELS,
    RUN_STATUSES,
    Briefing,
    Disclosure,
    Flag,
    RunRecord,
    SendResult,
    SignalRow,
    dart_link,
)

D = date(2026, 8, 25)


def make_disclosure(**kw: object) -> Disclosure:
    base: dict[str, object] = {
        "rcept_dt": date(2026, 8, 22),
        "report_nm": "전환사채권발행결정",
        "rcept_no": "20260822000123",
        "flr_nm": "가비아",
        "corrected": False,
    }
    base.update(kw)
    return Disclosure(**base)  # type: ignore[arg-type]


def make_briefing(**kw: object) -> Briefing:
    base: dict[str, object] = {
        "d": D,
        "strategy": "mtf",
        "ticker": "079940",
        "name": "가비아",
        "corp_code": "00123456",
        "level": "red",
        "flags": (
            Flag(rule="cb", level="red", rcept_no="20260822000123", report_nm="전환사채권발행결정"),
        ),
        "disclosures": (make_disclosure(),),
    }
    base.update(kw)
    return Briefing(**base)  # type: ignore[arg-type]


# ── 링크 ────────────────────────────────────────────────────────


def test_dart_link_points_to_viewer() -> None:
    assert dart_link("20260822000123") == (
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260822000123"
    )


def test_briefing_link_delegates() -> None:
    assert make_briefing().link("20260822000123").endswith("rcpNo=20260822000123")


# ── 불변성 ──────────────────────────────────────────────────────


def test_briefing_is_frozen() -> None:
    """요약·오류는 `dataclasses.replace()`로 갈아끼운다 — 노드가 값을 슬쩍 바꾸지 못하게."""
    b = make_briefing()
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.level = "none"  # type: ignore[misc]
    b2 = dataclasses.replace(b, summary="요약")
    assert b.summary is None and b2.summary == "요약"


# ── ksb_briefings 행 변환 (F9 계약) ────────────────────────────


def test_briefing_to_row_matches_schema_columns() -> None:
    row = make_briefing().to_row()
    assert set(row) == {
        "d",
        "strategy",
        "ticker",
        "name",
        "corp_code",
        "level",
        "flags",
        "disclosures",
        "window_days",
        "summary",
        "anomaly",
        "insider",
        "flow",
        "news",
        "bodies",
        "flows",
    }
    assert row["d"] == "2026-08-25"
    assert row["level"] == "red"
    assert row["window_days"] == 30
    assert row["summary"] is None


def test_briefing_to_row_serialises_nested_dates_as_iso() -> None:
    """jsonb에 date 객체를 그대로 넣으면 supabase-py가 직렬화하지 못한다."""
    row = make_briefing().to_row()
    assert row["disclosures"] == [
        {
            "rcept_dt": "2026-08-22",
            "report_nm": "전환사채권발행결정",
            "rcept_no": "20260822000123",
            "flr_nm": "가비아",
            "corrected": False,
        }
    ]
    assert row["flags"] == [
        {
            "rule": "cb",
            "level": "red",
            "rcept_no": "20260822000123",
            "report_nm": "전환사채권발행결정",
        }
    ]


def test_briefing_error_is_not_a_column() -> None:
    """`error`는 ksb_runs.detail로 가지 ksb_briefings 열이 아니다."""
    row = make_briefing(level="error", error="HTTP 500").to_row()
    assert "error" not in row


def test_level_values_match_schema_check() -> None:
    assert LEVELS == ("red", "amber", "none", "unknown", "error")


# ── SignalRow — ksa_signals에서 읽는 쪽 (evidence 계약) ─────────


def test_signal_row_reads_evidence_defensively() -> None:
    """상위가 키를 바꿔도 메일 전체를 죽이지 않는다 (R8) — 없는 키는 빈 값."""
    s = SignalRow(d=D, strategy="mtf", ticker="079940", name="가비아", evidence={})
    assert s.conditions == ()
    assert s.close == 0 and s.change_pct == 0.0 and s.in_progress is False


def test_signal_row_reads_evidence_keys() -> None:
    ev = {
        "conditions": [{"label": "월봉 종가 > MA20", "ok": True, "actual": "9,500 vs 4,581"}],
        "price": {"close": 8420, "change_pct": 1.32},
        "meta": {"in_progress": True},
    }
    s = SignalRow(d=D, strategy="mtf", ticker="222040", name="코스맥스엔비티", evidence=ev)
    assert s.conditions == (("월봉 종가 > MA20", True, "9,500 vs 4,581"),)
    assert s.close == 8420 and s.change_pct == 1.32 and s.in_progress is True


# ── SendResult · RunRecord ──────────────────────────────────────


def test_send_result_defaults() -> None:
    r = SendResult(ok=False, error="SMTPAuthenticationError")
    assert r.sent_n == 0 and r.channel == "email"


def test_run_record_to_row_and_statuses() -> None:
    rec = RunRecord(
        data_date=D,
        signal_n=15,
        red_n=2,
        amber_n=3,
        error_n=0,
        dart_calls=16,
        summary_n=12,
        llm_tokens=8100,
        status="ok",
        detail={"x": 1},
    )
    row = rec.to_row()
    assert row["data_date"] == "2026-08-25" and row["status"] == "ok"
    assert row["detail"] == {"x": 1}
    assert RUN_STATUSES == (
        "ok",
        "no_signals",
        "gate_timeout",
        "dart_partial",
        "dart_failed",
        "send_failed",
    )


def test_run_record_allows_null_data_date() -> None:
    """게이트 실패 시 기준일을 모른다 — null로 남긴다."""
    rec = RunRecord(data_date=None, status="gate_timeout")
    assert rec.to_row()["data_date"] is None


# ── anomaly · insider (F4b, v2.0) ────────────────────────────────

from briefing.models import Anomaly, Insider  # noqa: E402


def test_briefing_to_row_includes_anomaly_and_insider_columns() -> None:
    b = make_briefing(
        anomaly=Anomaly(score=68, verdict="warning", summary="s", flags=("auditor_change",)),
        insider=Insider(
            signal="sell_cluster", sell_events=5, unique_sellers=3, net_change_shares=-100
        ),
    )
    row = b.to_row()
    assert row["anomaly"] == {
        "score": 68,
        "verdict": "warning",
        "summary": "s",
        "flags": ["auditor_change"],
    }
    assert (
        row["insider"]["signal"] == "sell_cluster" and row["insider"]["net_change_shares"] == -100
    )
    assert set(row) >= {"anomaly", "insider"}


def test_briefing_to_row_anomaly_insider_null_when_absent() -> None:
    row = make_briefing().to_row()
    assert row["anomaly"] is None and row["insider"] is None


# ── R8: evidence가 흔들려도 값만 비운다 ──────────────────────────
#
# 상위 `ksa_signals.evidence`는 우리가 통제하지 않는 계약이다. 아래 모양들이 실제로 온다.


def ev(payload: object) -> SignalRow:
    return SignalRow(d=D, strategy="mtf", ticker="079940", name="가비아", evidence=payload)  # type: ignore[arg-type]


def test_signal_row_survives_a_null_evidence() -> None:
    """DB가 jsonb를 null로 주는 날이 있다."""
    s = ev(None)
    assert s.conditions == () and s.close == 0 and s.change_pct == 0.0
    assert s.in_progress is False


def test_signal_row_reads_a_price_that_is_not_a_number() -> None:
    """`int("8,420")`은 예외다 — 방어하지 않으면 그날 메일이 통째로 사라진다."""
    s = ev({"price": {"close": "8,420", "change_pct": "n/a"}})
    assert s.close == 0 and s.change_pct == 0.0


def test_signal_row_accepts_numeric_strings() -> None:
    """쉼표 없는 숫자 문자열은 읽는다 — 상위가 문자열로 바꿔도 값은 살린다."""
    s = ev({"price": {"close": "8420", "change_pct": "1.32"}})
    assert s.close == 8420 and s.change_pct == 1.32


def test_signal_row_ignores_conditions_that_are_not_a_list() -> None:
    assert ev({"conditions": "정배열"}).conditions == ()
    assert ev({"conditions": {"label": "x"}}).conditions == ()


def test_signal_row_empties_only_the_missing_field_of_a_condition() -> None:
    s = ev({"conditions": [{"ok": True}, {"label": "월봉", "ok": True, "actual": "9,500"}]})
    assert s.conditions == (("", True, ""), ("월봉", True, "9,500"))


def test_signal_row_ignores_a_meta_that_is_not_a_dict() -> None:
    assert ev({"meta": "진행중"}).in_progress is False


# ── 수급 30일 (F17, v3.0) ────────────────────────────────────────
#
# 세 갈래 증거의 셋째. 씨피시스템 CB 공시일에 외국인이 11.3억을 팔고 개인이 11.3억을 샀다 —
# 공시와 뉴스만으로는 보이지 않는 사실이다.

from briefing.models import FlowDay, InvestorFlows  # noqa: E402


def flows(*rows: tuple[int, int | None, int | None, int | None]) -> InvestorFlows:
    return InvestorFlows(
        days=tuple(
            FlowDay(d=date(2026, 8, day), inst=i, foreign=f, indiv=p) for day, i, f, p in rows
        )
    )


def test_totals_sum_the_window() -> None:
    f = flows((25, 10, -20, 10), (26, 5, -30, 25))
    assert f.inst_total == 15 and f.foreign_total == -50 and f.indiv_total == 35


def test_totals_skip_nulls_without_counting_them_as_zero() -> None:
    """그 투자자 표에 종목이 없던 날과 0원이던 날은 다르다."""
    f = flows((25, None, 0, None), (26, 7, None, None))
    assert f.inst_total == 7
    assert f.foreign_total == 0  # 0원은 값이다
    assert f.indiv_total is None  # 값이 하나도 없으면 None


def test_totals_of_an_empty_window_are_none() -> None:
    assert InvestorFlows().inst_total is None


def test_on_finds_the_day_a_filing_landed() -> None:
    """공시일 당일 수급이 이 데이터를 모으는 이유다."""
    f = flows((25, 1, 2, 3), (26, 4, 5, 6))
    day = f.on(date(2026, 8, 26))
    assert day is not None and day.foreign == 5
    assert f.on(date(2026, 8, 27)) is None


def test_recent_takes_the_tail_since_days_are_ascending() -> None:
    f = flows((24, 1, 1, 1), (25, 2, 2, 2), (26, 3, 3, 3))
    assert [x.d.day for x in f.recent(2).days] == [25, 26]


def test_recent_of_zero_is_empty() -> None:
    assert flows((24, 1, 1, 1)).recent(0).days == ()


def test_to_json_keeps_the_series_in_order() -> None:
    rows = flows((25, 1, 2, 3), (26, 4, 5, 6)).to_json()
    assert [r["d"] for r in rows] == ["2026-08-25", "2026-08-26"]
    assert rows[1]["foreign"] == 5


def test_briefing_row_carries_flows_and_null_when_absent() -> None:
    b = make_briefing(flows=flows((26, 1, 2, 3)))
    assert b.to_row()["flows"] == [
        {"d": "2026-08-26", "inst": 1, "foreign": 2, "indiv": 3}
    ]
    assert make_briefing().to_row()["flows"] is None
