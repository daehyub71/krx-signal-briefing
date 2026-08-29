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
