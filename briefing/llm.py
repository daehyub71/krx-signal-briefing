"""Claude 호출 — 하루 1회 일괄 요약 (SPEC F14 · D11). I/O 층.

**LLM은 압축만 한다.** 코드가 사실을 다 모은 뒤 한 번 부른다 — 도구를 주지 않고, 루프도 돌리지
않는다 (D10). 프롬프트와 스키마는 도메인 층(`analysis.py`)이 소유하고 이 모듈은 나르기만 한다.

**있으면 좋은 층이다** (R12). 여기서 무슨 일이 나도 예외를 둘로 좁혀 던진다:

| 예외 | 뜻 | 메일 문구 |
|------|-----|-----------|
| `LlmUnavailable` | 키가 없다 — 고장이 아니라 "그 층이 오늘 없다" | `⚠ 요약 생성 실패 (키 없음)` |
| `LlmError` | 호출·응답 실패 (거부 · 절단 · 파싱 · 네트워크) | `⚠ 요약 생성 실패 (…)` |

둘 다 `summarize` 노드가 잡는다. **새는 예외 하나가 그날 메일 전체를 없앤다.**

조심할 것:
- **`stop_reason == "refusal"`을 content보다 먼저 본다.** Opus 5는 거부를 HTTP 200으로 준다.
- **`max_tokens` 절단은 반쪽 JSON이다.** 반쪽을 요약이라 부르지 않는다.
- **키를 예외·로그에 싣지 않는다** (N7). SDK 예외를 그대로 감싸지 말고 종류와 상태 코드만 적는다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import anthropic

from briefing import analysis, config

MODEL = "claude-opus-5"  # D11 — 사용자 결정
# 15종목 × 최대 2,000자면 출력만 2만 토큰이 넘는다 (F19). 4096으로는 잘린다.
# **이만큼을 논스트리밍으로 받으면 HTTP 타임아웃에 걸린다** — SDK가 스트리밍을 요구한다.
MAX_TOKENS = 32000
TIMEOUT = 300.0  # 초. 스트리밍이라 오래 걸려도 연결이 끊기지 않는다
RETRIES = 2

KEY = "ANTHROPIC_API_KEY"


class LlmUnavailable(Exception):  # noqa: N818 — Error로 끝내지 않는다: 고장이 아니라는 뜻이다
    """키가 없어 부를 수 없다 (R12). **고장이 아니다** — 그 층이 오늘 없을 뿐이다."""


class LlmError(Exception):
    """호출했지만 쓸 수 있는 응답을 못 받았다. 거부·절단·파싱 실패·네트워크·상태 오류."""


@dataclass(frozen=True, slots=True)
class Usage:
    """토큰 사용량 — `ksb_runs.llm_tokens`에 기록한다."""

    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class Reply:
    """검증 전 응답. 내용을 믿지 않는다 — `analysis.validate()`가 다시 본다 (N13)."""

    payload: dict[str, Any]
    usage: Usage


def client() -> Any:
    """SDK 클라이언트. **키가 없으면 `LlmUnavailable`** — 여기서 갈린다.

    Raises:
        LlmUnavailable: `ANTHROPIC_API_KEY`가 없다.
    """
    key = config.optional(KEY)
    if not key:
        raise LlmUnavailable(f"{KEY} 없음")
    return anthropic.Anthropic(api_key=key, timeout=TIMEOUT, max_retries=RETRIES)


def _text_of(response: Any) -> str:
    """첫 text 블록. 구조화 출력이라 여기에 JSON이 통째로 온다."""
    for block in response.content or []:
        if getattr(block, "type", "") == "text":
            return str(block.text)
    raise LlmError("응답에 text 블록이 없다")


def _check(response: Any) -> None:
    """읽기 전에 멈출 이유부터 본다. **거부는 HTTP 200으로 온다.**"""
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        raise LlmError(f"모델이 응답을 거부했다 (category={category})")
    if stop == "max_tokens":
        raise LlmError(f"max_tokens({MAX_TOKENS})에서 잘렸다 — JSON이 반쪽이다")


def _usage_of(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def summarize(items: Sequence[dict[str, Any]], *, api: Any = None) -> Reply:
    """종목 목록을 한 번에 요약한다 — **하루 1회, 한 번의 호출**.

    Args:
        items: `analysis.build_input()`이 만든 입력 — 공시 본문·뉴스·수급·코드 판정이 들어 있다.
        api: 클라이언트. 테스트가 대역을 넣는다. 없으면 `client()`로 만든다.

    Returns:
        검증 전 `Reply`. 호출자가 `analysis.validate()`로 다시 본다.

    Raises:
        LlmUnavailable: 키가 없다 (`api`를 넘기지 않았을 때).
        LlmError: 호출·응답 실패. **그 밖의 예외는 나가지 않는다.**
    """
    api = api or client()
    args: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": analysis.SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": json.dumps(list(items), ensure_ascii=False)}],
        "output_config": {"format": {"type": "json_schema", "schema": analysis.OUTPUT_SCHEMA}},
    }
    try:
        # **스트리밍으로 받는다.** 출력이 2만 토큰을 넘을 수 있어 논스트리밍이면
        # HTTP 타임아웃에 걸린다 (2026-08-30 실측: `APITimeoutError`).
        with api.messages.stream(**args) as stream:
            response = stream.get_final_message()
    except anthropic.APIError as exc:
        # 예외를 그대로 감싸면 URL·헤더가 딸려 온다. 종류와 상태 코드만 남긴다 (N7).
        code = getattr(exc, "status_code", None)
        raise LlmError(f"{type(exc).__name__}{f' {code}' if code else ''}") from None

    _check(response)
    try:
        payload = json.loads(_text_of(response))
    except json.JSONDecodeError as exc:
        raise LlmError(f"JSON 파싱 실패: {exc.msg}") from None
    if not isinstance(payload, dict):
        raise LlmError(f"최상위가 객체가 아니다: {type(payload).__name__}")
    return Reply(payload=payload, usage=_usage_of(response))
