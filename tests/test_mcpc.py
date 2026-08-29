"""mcpc — MCP stdio 세션 관리. SDK·Node 없이 가짜 세션으로 검사한다.

지키는 것 (SPEC D12·D15·R18):
  · 세션은 배치당 1회 열고 닫는다 — 호출마다 프로세스를 띄우지 않는다
  · 스레드 여럿이 동시에 불러도 한 번에 하나만 세션에 닿는다 (락)
  · 타임아웃·도구 오류·미기동은 각각 다른 예외로, 호출자는 종목 단위로 격리한다
  · **stdout 오염 같은 세션 파손은 서버를 죽은 것으로 표시**하고 이후 호출은 즉시 실패한다
    — 매달리지 않는다
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from briefing import mcpc
from briefing.mcpc import (
    SERVERS,
    McpCallError,
    McpProtocolError,
    McpServer,
    McpStartError,
    McpUnavailableError,
    Spec,
)

# ── 가짜 SDK 객체 (mcp 2.x 형태 — snake_case) ─────────────────────


@dataclass
class Text:
    type: str
    text: str


@dataclass
class Result:
    content: list[Text]
    is_error: bool = False


@dataclass
class ToolInfo:
    name: str


@dataclass
class Tools:
    tools: list[ToolInfo]


@dataclass
class FakeSession:
    """`ClientSession` 대역. 호출 기록·동시성 측정·정해진 반응."""

    tools: list[str] = field(default_factory=lambda: ["search_disclosures", "insider_signal"])
    replies: dict[str, Any] = field(default_factory=dict)  # tool → 문자열 | Result | Exception
    delay: float = 0.0
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    initialized: bool = False

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> Tools:
        return Tools([ToolInfo(n) for n in self.tools])

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
    ) -> Result:
        self.calls.append((name, arguments))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            reply = self.replies.get(name, '{"ok": true}')
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, Result):
                return reply
            return Result([Text("text", str(reply))])
        finally:
            self.in_flight -= 1


def connector_for(session: FakeSession, *, fail: Exception | None = None) -> Any:
    """세션을 내주는 가짜 커넥터. `fail`이면 기동 자체가 죽는다."""

    @asynccontextmanager
    async def connect(spec: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        if fail is not None:
            raise fail
        await session.initialize()
        yield session

    return connect


SPEC = Spec(name="fake", package="fake-mcp", version="1.0.0", env=(), required=())


@pytest.fixture
def server() -> Any:
    """시작된 서버. 테스트 끝에 닫는다."""
    started: list[McpServer] = []

    def make(session: FakeSession | None = None, spec: Spec = SPEC, **kw: Any) -> McpServer:
        s = McpServer(spec, connector=connector_for(session or FakeSession(), **kw))
        started.append(s)
        return s

    yield make
    for s in started:
        s.close()


# ── 세션 수명 ─────────────────────────────────────────────────────


def test_start_opens_session_once_and_lists_tools(server: Any) -> None:
    fake = FakeSession()
    s = server(fake)
    s.start(timeout=5)
    assert s.available and fake.initialized
    assert s.tools == ["search_disclosures", "insider_signal"]
    s.call("search_disclosures", {"corp": "x"})
    s.call("insider_signal", {"corp": "x"})
    assert len(fake.calls) == 2  # 프로세스 재기동 없이 같은 세션


def test_close_is_idempotent_and_marks_unavailable(server: Any) -> None:
    s = server()
    s.start(timeout=5)
    s.close()
    s.close()
    assert not s.available
    with pytest.raises(McpUnavailableError):
        s.call("search_disclosures")


def test_call_before_start_fails_fast(server: Any) -> None:
    s = server()
    with pytest.raises(McpUnavailableError):
        s.call("search_disclosures")


# ── 기동 실패 (D15 — 서버 미기동도 생략 경로) ─────────────────────


def test_start_failure_raises_and_stays_unavailable(server: Any) -> None:
    s = server(fail=RuntimeError("자격증명이 설정되지 않았습니다"))
    with pytest.raises(McpStartError, match="자격증명"):
        s.start(timeout=5)
    assert not s.available


def test_missing_required_env_fails_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 없으면 npx를 띄우지도 않는다 — naver는 키 없이 기동 자체를 거부한다 (실측)."""
    monkeypatch.delenv("NCP_APIGW_API_KEY_ID", raising=False)
    spec = Spec(
        name="naver",
        package="x",
        version="1",
        env=("NCP_APIGW_API_KEY_ID",),
        required=("NCP_APIGW_API_KEY_ID",),
    )
    spawned: list[Spec] = []

    @asynccontextmanager
    async def connect(sp: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        spawned.append(sp)
        yield FakeSession()

    s = McpServer(spec, connector=connect)
    with pytest.raises(McpStartError, match="NCP_APIGW_API_KEY_ID"):
        s.start(timeout=5)
    assert spawned == []


def test_env_passes_only_listed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버 프로세스에는 필요한 키만 넘긴다 — 다른 시크릿이 새지 않게."""
    monkeypatch.setenv("DART_API_KEY", "k1")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    seen: dict[str, str] = {}

    @asynccontextmanager
    async def connect(sp: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        seen.update(env)
        yield FakeSession()

    spec = Spec(
        name="dart", package="x", version="1", env=("DART_API_KEY",), required=("DART_API_KEY",)
    )
    s = McpServer(spec, connector=connect)
    s.start(timeout=5)
    s.close()
    assert seen["DART_API_KEY"] == "k1" and "GMAIL_APP_PASSWORD" not in seen
    assert "PATH" in seen  # npx를 찾으려면 PATH는 있어야 한다


# ── 호출 ─────────────────────────────────────────────────────────


def test_call_returns_text_and_call_json_parses(server: Any) -> None:
    fake = FakeSession(replies={"search_disclosures": '{"items": [1, 2]}'})
    s = server(fake)
    s.start(timeout=5)
    assert s.call("search_disclosures", {"corp": "00126380"}) == '{"items": [1, 2]}'
    assert s.call_json("search_disclosures", {"corp": "00126380"}) == {"items": [1, 2]}
    assert fake.calls[0] == ("search_disclosures", {"corp": "00126380"})


def test_tool_error_result_raises_call_error(server: Any) -> None:
    """korea-stock-mcp는 키가 없으면 is_error=True + 본문으로 답한다 (실측)."""
    fake = FakeSession(
        tools=["get_stock_trade_info"],
        replies={"get_stock_trade_info": Result([Text("text", "There is no KRX API KEY")], True)},
    )
    s = server(fake)
    s.start(timeout=5)
    with pytest.raises(McpCallError, match="KRX API KEY"):
        s.call("get_stock_trade_info", {})
    assert s.available  # 도구 오류는 세션 파손이 아니다


def test_unknown_tool_fails_without_calling(server: Any) -> None:
    s = server()
    s.start(timeout=5)
    with pytest.raises(McpCallError, match="없는 도구"):
        s.call("nope")


def test_timeout_raises_call_error_and_server_survives(server: Any) -> None:
    fake = FakeSession(delay=0.5)
    s = server(fake)
    s.start(timeout=5)
    with pytest.raises(McpCallError, match="타임아웃"):
        s.call("search_disclosures", timeout=0.05)
    assert s.available


def test_calls_are_serialized_across_threads(server: Any) -> None:
    """fan-out 스레드 N개가 세션 하나를 공유한다 — 동시에 닿으면 stdio 프레임이 섞인다."""
    fake = FakeSession(delay=0.02)
    s = server(fake)
    s.start(timeout=5)
    threads = [
        threading.Thread(target=s.call, args=("search_disclosures", {"i": i})) for i in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fake.calls) == 6 and fake.max_in_flight == 1


# ── R18 — 세션 파손 격리 ─────────────────────────────────────────


def test_protocol_error_marks_dead_and_next_call_fails_fast(server: Any) -> None:
    """서버가 stdout에 로그를 찍으면 SDK가 프레임 파싱 예외를 낸다. 그 뒤로 매달리면 안 된다."""
    fake = FakeSession(
        replies={"search_disclosures": ValueError("Unexpected non-JSON line on stdout")}
    )
    s = server(fake)
    s.start(timeout=5)
    with pytest.raises(McpProtocolError, match="non-JSON"):
        s.call("search_disclosures")
    assert not s.available
    t0 = time.perf_counter()
    with pytest.raises(McpUnavailableError):
        s.call("insider_signal")
    assert time.perf_counter() - t0 < 0.1
    assert len(fake.calls) == 1  # 죽은 뒤엔 세션에 닿지 않는다


def test_failure_in_one_server_does_not_touch_another(server: Any) -> None:
    bad = FakeSession(replies={"search_disclosures": ValueError("broken")})
    good = FakeSession()
    a, b = server(bad), server(good)
    a.start(timeout=5)
    b.start(timeout=5)
    with pytest.raises(McpProtocolError):
        a.call("search_disclosures")
    assert b.call("search_disclosures") == '{"ok": true}' and b.available


# ── 레지스트리 · 서버 정의 ─────────────────────────────────────────


def test_server_specs_are_pinned() -> None:
    """버전 고정 (N14). 2026-08-29 실측 기동 버전."""
    assert SERVERS["dart"].package == "korean-dart-mcp" and SERVERS["dart"].version == "0.10.1"
    assert (
        SERVERS["naver"].package == "@isnow890/naver-search-mcp"
        and SERVERS["naver"].version == "1.0.50"
    )
    # korea-stock-mcp는 배치에서 뺐다 (D14 v2) — 시총은 상위 ksc_tickers에서 SQL로 읽는다
    assert set(SERVERS) == {"dart", "naver"}
    assert SERVERS["dart"].required == ("DART_API_KEY",)
    assert set(SERVERS["naver"].required) == {"NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY"}


def test_npx_command_pins_version() -> None:
    cmd, args = mcpc.npx_command(SERVERS["dart"])
    assert cmd == "npx" and args == ["-y", "korean-dart-mcp@0.10.1"]


def test_registry_starts_lazily_and_closes_all(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSession()
    monkeypatch.setattr(mcpc, "_connector", connector_for(fake))
    monkeypatch.setattr(mcpc, "SERVERS", {"fake": SPEC})
    mcpc.close_all()
    s1 = mcpc.get("fake")
    s2 = mcpc.get("fake")
    assert s1 is s2 and s1.available and fake.initialized
    mcpc.close_all()
    assert not s1.available


def test_registry_get_raises_start_error_and_caches_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """한 번 못 뜬 서버를 종목마다 다시 띄우려 들면 안 된다 — 15번 npx."""
    attempts = {"n": 0}

    @asynccontextmanager
    async def connect(sp: Spec, env: dict[str, str]) -> AsyncIterator[FakeSession]:
        attempts["n"] += 1
        if (
            attempts["n"] > 0
        ):  # 항상 실패 — mypy가 아래 yield를 도달 불가로 보지 않게 런타임 조건으로
            raise RuntimeError("boom")
        yield FakeSession()

    monkeypatch.setattr(mcpc, "_connector", connect)
    monkeypatch.setattr(mcpc, "SERVERS", {"fake": SPEC})
    mcpc.close_all()
    with pytest.raises(McpStartError):
        mcpc.get("fake")
    with pytest.raises(McpStartError):
        mcpc.get("fake")
    assert attempts["n"] == 1
    mcpc.close_all()
