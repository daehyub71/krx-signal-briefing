"""MCP stdio 클라이언트 — 남이 만든 MCP 서버를 배치의 데이터 소스로 부른다 (SPEC D12·D15·N14·R18).

**MCP 서버는 데이터 소스다.** 도구 호출 순서·인자는 코드가 정하고, LLM에는 도구를 주지 않는다.

구조:
- 서버마다 **전용 이벤트 루프 스레드** 하나. 그 위에서 `npx -y <pkg>@<ver>`를 stdio로 띄우고
  `ClientSession`을 배치당 **1회** 열어 둔다 (`start()`) — 호출마다 프로세스를 띄우지 않는다.
- 노드(LangGraph `Send` fan-out은 스레드 병렬)는 동기 `call()`로 부른다. **락으로 직렬화**한다 —
  세션 하나에 동시에 닿으면 stdio 프레임이 섞인다.
- 실패는 넷으로 나눈다. 호출자는 종목 단위로 격리한다 (생략 또는 폴백, D15).

| 예외 | 뜻 | 서버 상태 |
|------|-----|----------|
| `McpStartError` | 기동 실패 — 키 없음, npx 실패, 서버가 스스로 종료 | 죽음 (다시 띄우지 않는다) |
| `McpCallError` | 도구가 `is_error`로 답함 · 없는 도구 · 타임아웃 | 살아 있음 |
| `McpProtocolError` | 세션 파손 — stdout 오염·파이프 끊김 | 죽음 — 이후 즉시 Unavailable |
| `McpUnavailableError` | 안 떴거나 죽은 서버를 부름 | — |

MCP 파이썬 SDK 2.x는 응답 필드가 snake_case다 (`tool.input_schema`, `result.is_error`) —
1.x 문서와 다르다.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError as SdkMcpError

# 서버 프로세스에 항상 넘기는 환경변수.
# npx를 찾으려면 PATH가, 캐시(~/.korean-dart-mcp)를 두려면 HOME이 필요하다.
BASE_ENV = ("PATH", "HOME")

DEFAULT_TIMEOUT = 30.0
START_TIMEOUT = 90.0  # korean-dart-mcp 콜드스타트 10.9초 실측 + CI 여유


@dataclass(frozen=True, slots=True)
class Spec:
    """MCP 서버 정의. 버전은 고정한다 (N14)."""

    name: str
    package: str
    version: str
    env: tuple[str, ...]  # 넘길 환경변수 (있으면)
    required: tuple[str, ...]  # 없으면 띄우지 않는다


# 2026-08-29 로컬 기동 실측 버전. 올릴 때는 계약 테스트(표본 JSON)를 다시 돌린다.
# korea-stock-mcp는 **배치에서 뺐다** (D14 v2, 2026-08-29): 시총·상장주식수는 상위
# krx-stock-charts가 pykrx로 매일 ksc_tickers에 채우고(상위 SPEC F8) 우리는 SQL로 읽는다 —
# KRX OPEN API 키가 필요 없고 호출도 0회다. 대화형(Claude Desktop)으로는 그대로 쓸 수 있다.
SERVERS: dict[str, Spec] = {
    "dart": Spec(
        name="dart",
        package="korean-dart-mcp",
        version="0.10.1",
        env=("DART_API_KEY",),
        required=("DART_API_KEY",),
    ),
    "naver": Spec(
        name="naver",
        package="@isnow890/naver-search-mcp",
        version="1.0.50",
        env=("NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY"),
        # 키가 없으면 서버가 기동 자체를 거부한다 (실측) — 띄우기 전에 거른다
        required=("NCP_APIGW_API_KEY_ID", "NCP_APIGW_API_KEY"),
    ),
}


class McpError(RuntimeError):
    """MCP 계층의 모든 실패."""


class McpStartError(McpError):
    """서버를 띄우지 못했다."""


class McpCallError(McpError):
    """도구 호출이 실패했다 — 서버는 살아 있다."""


class McpProtocolError(McpError):
    """세션이 파손됐다 — 서버를 죽은 것으로 표시한다 (R18)."""


class McpUnavailableError(McpError):
    """안 떴거나 죽은 서버를 불렀다."""


def npx_command(spec: Spec) -> tuple[str, list[str]]:
    """`npx -y <package>@<version>` — 버전 고정."""
    return "npx", ["-y", f"{spec.package}@{spec.version}"]


def env_for(spec: Spec) -> dict[str, str]:
    """서버 프로세스 환경 — 기본 키 + 서버가 쓰는 키만. 다른 시크릿은 넘기지 않는다."""
    keys = BASE_ENV + spec.env
    return {k: os.environ[k] for k in keys if k in os.environ}


@asynccontextmanager
async def _connector(spec: Spec, env: dict[str, str]) -> AsyncIterator[Any]:
    """실제 SDK 커넥터 — npx stdio 프로세스 + 초기화된 `ClientSession`을 내준다."""
    cmd, args = npx_command(spec)
    params = StdioServerParameters(command=cmd, args=args, env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


Connector = Callable[[Spec, dict[str, str]], Any]


class McpServer:
    """MCP 서버 하나의 세션. `start()` → `call()`… → `close()`."""

    def __init__(self, spec: Spec, *, connector: Connector | None = None) -> None:
        self.spec = spec
        self._connector: Connector = connector or _connector
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._tools: list[str] = []
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._dead: str = ""

    # ── 상태 ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """호출할 수 있는 상태인가."""
        return self._session is not None and not self._dead

    @property
    def tools(self) -> list[str]:
        """서버가 내놓은 도구 이름."""
        return list(self._tools)

    # ── 수명 ────────────────────────────────────────────────────

    def start(self, timeout: float = START_TIMEOUT) -> None:
        """세션을 연다. 실패하면 `McpStartError` — 다시 띄우지 않는다.

        Args:
            timeout: 기동 대기 상한(초). korean-dart-mcp 콜드스타트는 10초대다.

        Raises:
            McpStartError: 필수 키 없음 · npx/서버 실패 · 대기 초과.
        """
        missing = [k for k in self.spec.required if not os.environ.get(k, "").strip()]
        if missing:
            self._dead = f"환경변수 없음: {', '.join(missing)}"
            raise McpStartError(f"[{self.spec.name}] {self._dead} — 서버를 띄우지 않는다")
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name=f"mcp-{self.spec.name}", daemon=True
        )
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._run(), self._loop)
        if not self._ready.wait(timeout):
            self._dead = f"기동 {timeout:.0f}초 초과"
            self._shutdown()
            raise McpStartError(f"[{self.spec.name}] {self._dead}")
        if self._error is not None:
            self._dead = f"기동 실패: {self._error}"
            self._shutdown()
            raise McpStartError(f"[{self.spec.name}] {self._dead}") from None
        pkg = f"{self.spec.package}@{self.spec.version}"
        print(f"[mcp] {self.spec.name} {pkg} 기동 · 도구 {len(self._tools)}개")

    async def _run(self) -> None:
        """루프 스레드 안에서 세션을 열고, 닫으라는 신호까지 붙들고 있는다."""
        self._stop = asyncio.Event()
        try:
            async with self._connector(self.spec, env_for(self.spec)) as session:
                self._tools = [t.name for t in (await session.list_tools()).tools]
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 — 기동 실패를 호출 스레드에 그대로 전달한다
            self._error = exc
            self._ready.set()
        finally:
            self._session = None
            self._closed.set()

    def close(self) -> None:
        """세션과 프로세스를 닫는다. 여러 번 불러도 안전하다."""
        if self._loop is None:
            return
        if self._stop is not None and self._session is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._closed.wait(10)
        self._shutdown()

    def _shutdown(self) -> None:
        loop, thread = self._loop, self._thread
        self._session = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(5)
        self._loop = None
        self._thread = None

    # ── 호출 ────────────────────────────────────────────────────

    def call(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> str:
        """도구를 부르고 텍스트 본문을 돌려준다. 스레드 여럿이 불러도 한 번에 하나만 세션에 닿는다.

        Args:
            tool: 도구 이름.
            args: 도구 인자.
            timeout: 응답 대기 상한(초).

        Returns:
            `text` 콘텐츠를 이어 붙인 문자열 (보통 JSON).

        Raises:
            McpUnavailableError: 안 떴거나 죽은 서버.
            McpCallError: 없는 도구 · `is_error` 응답 · 타임아웃 · 서버 오류 응답.
            McpProtocolError: 세션 파손 — 서버를 죽은 것으로 표시한다.
        """
        with self._lock:
            if not self.available or self._loop is None:
                raise McpUnavailableError(
                    f"[{self.spec.name}] 사용 불가: {self._dead or '기동 전'}"
                )
            if self._tools and tool not in self._tools:
                raise McpCallError(f"[{self.spec.name}] 없는 도구: {tool}")
            fut = asyncio.run_coroutine_threadsafe(
                self._session.call_tool(tool, args, read_timeout_seconds=timeout), self._loop
            )
            try:
                # SDK read_timeout과 별개로 우리 쪽에도 같은 상한 — 세션이 매달려도 노드는 풀린다
                result = fut.result(timeout)
            except concurrent.futures.TimeoutError:
                fut.cancel()
                raise McpCallError(f"[{self.spec.name}] {tool} 타임아웃 {timeout:.0f}초") from None
            except SdkMcpError as exc:
                raise McpCallError(f"[{self.spec.name}] {tool} 서버 오류: {exc}") from None
            except Exception as exc:  # 프레임 파싱 실패 · 파이프 끊김 — 세션은 더 못 쓴다
                self._dead = f"{type(exc).__name__}: {exc}"
                raise McpProtocolError(f"[{self.spec.name}] 세션 파손 — {self._dead}") from None
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if getattr(result, "is_error", False):
            raise McpCallError(f"[{self.spec.name}] {tool} 실패: {text[:300]}")
        return text

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> Any:
        """`call()` 결과를 JSON으로 푼다."""
        text = self.call(tool, args, timeout=timeout)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise McpCallError(
                f"[{self.spec.name}] {tool} 응답이 JSON이 아니다: {text[:120]!r}"
            ) from exc


# ── 레지스트리 — 배치당 서버 하나씩 ────────────────────────────────

_servers: dict[str, McpServer] = {}
_registry_lock = threading.Lock()


def get(name: str) -> McpServer:
    """이름으로 서버를 얻는다. 처음 부를 때 띄운다. 한 번 실패한 서버는 다시 띄우지 않는다.

    Raises:
        McpStartError: 기동 실패 (첫 호출 때, 그리고 이후에도 같은 예외).
    """
    with _registry_lock:
        server = _servers.get(name)
        if server is None:
            server = McpServer(SERVERS[name], connector=_connector)
            _servers[name] = server
            server.start()
        elif not server.available:
            raise McpStartError(f"[{name}] 사용 불가: {server._dead or '닫힘'}")
        return server


def close_all() -> None:
    """모든 서버를 닫는다. `main`이 끝날 때 부른다."""
    with _registry_lock:
        for server in _servers.values():
            server.close()
        _servers.clear()
