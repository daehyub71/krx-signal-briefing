"""dart — OpenDART HTTP 클라이언트. `urlopen`을 mock한다. 실제 네트워크 없음.

지키는 것:
  · 013은 오류가 아니라 공시 0건
  · 020(한도) · 800(점검) · 5xx · 타임아웃은 1회 재시도 후 예외
  · 010/011(키 오류)은 재시도하지 않는다 — 다시 불러도 같다
  · **예외 메시지와 stdout 어디에도 키가 없다** (N7)
"""

from __future__ import annotations

import io
import json
import urllib.parse
from collections.abc import Callable
from datetime import date
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from briefing import dart
from briefing.dart import DartError, DartMaintenanceError, DartRateLimitError
from briefing.models import Disclosure

KEY = "0123456789abcdef0123456789abcdef01234567"  # 40자 가짜 키
CORP = "00126380"
BGN, END = date(2026, 7, 27), date(2026, 8, 26)


class FakeResponse:
    """`urlopen()`이 돌려주는 것 — 컨텍스트 매니저 + read()."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def body(status: str, items: list[dict[str, Any]] | None = None, **extra: Any) -> bytes:
    d: dict[str, Any] = {"status": status, "message": "정상" if status == "000" else "오류"}
    if items is not None:
        d["list"] = items
        d["total_count"] = extra.pop("total_count", len(items))
    d.update(extra)
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


def item(
    rcept_no: str = "20260822000123",
    report_nm: str = "전환사채권발행결정",
    rcept_dt: str = "20260822",
    flr_nm: str = "가비아",
) -> dict[str, str]:
    return {
        "rcept_no": rcept_no,
        "report_nm": report_nm,
        "rcept_dt": rcept_dt,
        "flr_nm": flr_nm,
        "corp_code": CORP,
        "corp_name": flr_nm,
        "stock_code": "079940",
        "rm": "",
    }


class Recorder:
    """urlopen 대역. 호출된 URL을 기록하고 준비된 응답/예외를 순서대로 돌려준다."""

    def __init__(self, *outcomes: bytes | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []

    def __call__(self, req: Any, timeout: float | None = None) -> FakeResponse:
        self.urls.append(req.full_url if hasattr(req, "full_url") else str(req))
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return FakeResponse(out)

    def query(self, i: int = 0) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.urls[i]).query))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(dart, "sleep", lambda s: slept.append(s))
    monkeypatch.setenv("DART_API_KEY", KEY)
    return slept


def use(monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> Recorder:
    monkeypatch.setattr(dart, "urlopen", rec)
    return rec


# ── list.json 정상 ──────────────────────────────────────────────


def test_fetch_disclosures_parses_items(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(
        monkeypatch,
        Recorder(body("000", [item(), item("20260807000001", "분기보고서", "20260807")])),
    )
    out = dart.fetch_disclosures(CORP, BGN, END)
    assert out == [
        Disclosure(
            rcept_dt=date(2026, 8, 22),
            report_nm="전환사채권발행결정",
            rcept_no="20260822000123",
            flr_nm="가비아",
        ),
        Disclosure(
            rcept_dt=date(2026, 8, 7),
            report_nm="분기보고서",
            rcept_no="20260807000001",
            flr_nm="가비아",
        ),
    ]
    q = rec.query()
    assert rec.urls[0].startswith("https://opendart.fss.or.kr/api/list.json?")
    assert q["crtfc_key"] == KEY and q["corp_code"] == CORP
    assert q["bgn_de"] == "20260727" and q["end_de"] == "20260826" and q["page_count"] == "100"
    assert len(rec.urls) == 1 and no_sleep == []


def test_013_means_zero_disclosures_not_error(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(monkeypatch, Recorder(body("013")))
    assert dart.fetch_disclosures(CORP, BGN, END) == []
    assert len(rec.urls) == 1


def test_warns_when_total_exceeds_page(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """30일에 100건을 넘는 종목은 없다고 보지만, 넘으면 조용히 잘라서는 안 된다 (F4)."""
    use(monkeypatch, Recorder(body("000", [item()], total_count=140)))
    dart.fetch_disclosures(CORP, BGN, END)
    assert "140" in capsys.readouterr().out


# ── 재시도 ──────────────────────────────────────────────────────


def test_020_retries_once_then_raises_rate_limit(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(monkeypatch, Recorder(body("020"), body("020")))
    with pytest.raises(DartRateLimitError, match="020"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2 and len(no_sleep) == 1


def test_800_retries_once_then_raises_maintenance(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(monkeypatch, Recorder(body("800"), body("800")))
    with pytest.raises(DartMaintenanceError, match="800"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_5xx_retries_once_then_raises(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    err = HTTPError(
        "https://opendart.fss.or.kr/api/list.json", 502, "Bad Gateway", Message(), io.BytesIO(b"")
    )
    rec = use(monkeypatch, Recorder(err, err))
    with pytest.raises(DartError, match="502"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_timeout_retries_once_then_raises(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(
        monkeypatch,
        Recorder(URLError(TimeoutError("timed out")), URLError(TimeoutError("timed out"))),
    )
    with pytest.raises(DartError, match="timed out"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_transient_failure_then_success(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """첫 시도가 죽고 두 번째가 살면 정상 결과다 — 재시도가 실제로 값을 돌려준다."""
    rec = use(monkeypatch, Recorder(URLError("reset"), body("000", [item()])))
    assert len(dart.fetch_disclosures(CORP, BGN, END)) == 1
    assert len(rec.urls) == 2 and len(no_sleep) == 1


def test_key_error_does_not_retry(no_sleep: list[float], monkeypatch: pytest.MonkeyPatch) -> None:
    """010/011은 다시 불러도 같다."""
    rec = use(monkeypatch, Recorder(body("011")))
    with pytest.raises(DartError, match="011"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 1 and no_sleep == []


# ── 키 마스킹 (N7) ──────────────────────────────────────────────


def _assert_no_key(text: str) -> None:
    assert KEY not in text, "키가 새어 나왔다"


@pytest.mark.parametrize(
    "make",
    [
        lambda: URLError(
            f"cannot reach https://opendart.fss.or.kr/api/list.json?crtfc_key={KEY}&x=1"
        ),
        lambda: HTTPError(
            f"https://opendart.fss.or.kr/api/list.json?crtfc_key={KEY}",
            500,
            "boom",
            Message(),
            None,
        ),
    ],
)
def test_exception_message_never_contains_key(
    no_sleep: list[float],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    make: Callable[[], BaseException],
) -> None:
    use(monkeypatch, Recorder(make(), make()))
    with pytest.raises(DartError) as info:
        dart.fetch_disclosures(CORP, BGN, END)
    _assert_no_key(str(info.value))
    _assert_no_key(repr(info.value))
    _assert_no_key(capsys.readouterr().out)


def test_status_error_message_never_contains_key(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use(
        monkeypatch,
        Recorder(body("020", message=f"limit for {KEY}"), body("020", message=f"limit for {KEY}")),
    )
    with pytest.raises(DartRateLimitError) as info:
        dart.fetch_disclosures(CORP, BGN, END)
    _assert_no_key(str(info.value))
    _assert_no_key(capsys.readouterr().out)


def test_mask_helper() -> None:
    assert dart.mask(f"a={KEY}&b", KEY) == "a=***&b"
    assert dart.mask("nothing", KEY) == "nothing"


# ── corpCode.xml ────────────────────────────────────────────────


def test_fetch_corp_codes_returns_raw_bytes(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """파싱은 corp.py 몫이다 — 여기서는 바이트만 돌려준다 (오류 본문 판별도 corp.py)."""
    rec = use(monkeypatch, Recorder(b"PK\x03\x04fake-zip"))
    assert dart.fetch_corp_codes() == b"PK\x03\x04fake-zip"
    assert rec.urls[0].startswith("https://opendart.fss.or.kr/api/corpCode.xml?")
    assert rec.query()["crtfc_key"] == KEY


def test_fetch_corp_codes_retries_on_network_error(
    no_sleep: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = use(monkeypatch, Recorder(URLError("reset"), b"PK\x03\x04ok"))
    assert dart.fetch_corp_codes() == b"PK\x03\x04ok"
    assert len(rec.urls) == 2


def test_missing_key_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DART_API_KEY"):
        dart.fetch_disclosures(CORP, BGN, END)
