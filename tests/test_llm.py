"""llm — Claude 호출 (F14 · D11). I/O 층이라 SDK는 전부 mock이다.

**이 층은 있으면 좋은 층이다** (R12). 여기서 무슨 일이 나도 예외가 밖으로 새면 안 된다 —
`analyze` 노드가 잡을 수 있도록 `LlmUnavailable`·`LlmError` 둘로 좁혀 던진다.
새는 예외 하나가 그날 메일 전체를 없앤다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from briefing import analysis, llm

ITEMS = [{"ticker": "079940", "name": "가비아", "level": "red", "disclosures": []}]


class FakeStream:
    """`messages.stream()`이 돌려주는 컨텍스트 매니저 대역."""

    def __init__(self, reply: Any, exc: Exception | None) -> None:
        self.reply, self.exc = reply, exc

    def __enter__(self) -> FakeStream:
        if self.exc is not None:
            raise self.exc
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        return self.reply


class FakeMessages:
    """`client.messages` 대역. 마지막 호출 인자를 남긴다.

    **스트리밍으로 부른다** — 출력이 2만 토큰을 넘을 수 있어 논스트리밍이면
    HTTP 타임아웃에 걸린다 (2026-08-30 실측).
    """

    def __init__(self, reply: Any = None, exc: Exception | None = None) -> None:
        self.reply, self.exc = reply, exc
        self.kwargs: dict[str, Any] = {}

    def stream(self, **kwargs: Any) -> FakeStream:
        self.kwargs = kwargs
        return FakeStream(self.reply, self.exc)


def api(reply: Any = None, exc: Exception | None = None) -> Any:
    return SimpleNamespace(messages=FakeMessages(reply, exc))


def reply(
    payload: Any = None, *, stop_reason: str = "end_turn", stop_details: Any = None
) -> Any:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=stop_details,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=5100, output_tokens=420),
        model=llm.MODEL,
    )


def status_error(code: int) -> anthropic.APIStatusError:
    """SDK의 상태 오류 하나. 생성자가 요구하는 것만 채운다."""
    request = SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages")
    response = SimpleNamespace(status_code=code, headers={}, request=request)
    return anthropic.APIStatusError("boom", response=response, body=None)  # type: ignore[arg-type]


# ── 성공 경로 ────────────────────────────────────────────────────


def test_summarize_returns_the_payload_and_token_counts() -> None:
    out = llm.summarize(ITEMS, api=api(reply({"items": [{"ticker": "079940", "summary": "x"}]})))
    assert out.payload == {"items": [{"ticker": "079940", "summary": "x"}]}
    assert out.usage.input_tokens == 5100 and out.usage.output_tokens == 420
    assert out.usage.total == 5520


def test_summarize_sends_the_house_prompt_and_schema() -> None:
    """프롬프트·스키마는 `analysis.py`가 소유한다 — llm은 나르기만 한다 (3층 분리)."""
    a = api(reply({"items": []}))
    llm.summarize(ITEMS, api=a)
    kw = a.messages.kwargs
    assert kw["model"] == llm.MODEL
    assert kw["max_tokens"] == llm.MAX_TOKENS
    assert kw["system"] == analysis.SYSTEM_PROMPT
    assert kw["output_config"]["format"]["schema"] == analysis.OUTPUT_SCHEMA
    assert kw["output_config"]["format"]["type"] == "json_schema"


def test_summarize_sends_the_items_as_the_only_user_content() -> None:
    """입력은 제목·날짜·등급뿐이다 — 본문을 넣지 않는다 (F14)."""
    a = api(reply({"items": []}))
    llm.summarize(ITEMS, api=a)
    (msg,) = a.messages.kwargs["messages"]
    assert msg["role"] == "user"
    assert json.loads(msg["content"]) == ITEMS


# ── 실패 경로 — 전부 LlmError로 좁힌다 ───────────────────────────


def test_refusal_is_an_error_not_a_summary() -> None:
    """Opus 5는 거부를 HTTP 200으로 준다 — content를 읽기 전에 `stop_reason`을 본다."""
    r = reply(
        {"items": [{"ticker": "079940", "summary": "지어낸 것"}]},
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber", explanation="nope"),
    )
    with pytest.raises(llm.LlmError, match="거부"):
        llm.summarize(ITEMS, api=api(r))


def test_refusal_without_details_still_errors() -> None:
    with pytest.raises(llm.LlmError):
        llm.summarize(ITEMS, api=api(reply({"items": []}, stop_reason="refusal")))


def test_truncated_output_is_an_error_not_half_a_summary() -> None:
    """`max_tokens`에서 잘리면 JSON이 반쪽이다. 반쪽을 요약이라 부르지 않는다."""
    with pytest.raises(llm.LlmError, match="max_tokens"):
        llm.summarize(ITEMS, api=api(reply('{"items": [{"ticker"', stop_reason="max_tokens")))


def test_malformed_json_is_an_error() -> None:
    with pytest.raises(llm.LlmError, match="JSON"):
        llm.summarize(ITEMS, api=api(reply("이건 JSON이 아니다")))


def test_a_json_array_at_the_top_level_is_an_error() -> None:
    """스키마는 객체를 약속한다. 배열이 오면 `validate`가 읽을 수 없다."""
    with pytest.raises(llm.LlmError):
        llm.summarize(ITEMS, api=api(reply([{"ticker": "079940"}])))


def test_a_response_without_a_text_block_is_an_error() -> None:
    empty = SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        model=llm.MODEL,
    )
    with pytest.raises(llm.LlmError):
        llm.summarize(ITEMS, api=api(empty))


@pytest.mark.parametrize(
    "exc",
    [
        anthropic.APITimeoutError(request=SimpleNamespace()),  # type: ignore[arg-type]
        anthropic.APIConnectionError(request=SimpleNamespace()),  # type: ignore[arg-type]
    ],
)
def test_network_failures_become_llm_errors(exc: Exception) -> None:
    with pytest.raises(llm.LlmError):
        llm.summarize(ITEMS, api=api(exc=exc))


@pytest.mark.parametrize("code", [400, 429, 500])
def test_api_status_errors_become_llm_errors(code: int) -> None:
    with pytest.raises(llm.LlmError):
        llm.summarize(ITEMS, api=api(exc=status_error(code)))


def test_the_api_key_never_reaches_an_error_message() -> None:
    """키는 어떤 경로로도 로그·예외에 실리지 않는다 (N7)."""
    secret = "sk-ant-" + "x" * 40
    exc = status_error(401)
    with pytest.raises(llm.LlmError) as caught:
        llm.summarize(ITEMS, api=api(exc=exc))
    assert secret not in str(caught.value)


# ── 키 없음 (R12) — 실패가 아니라 "그 층이 오늘 없다" ────────────


def test_missing_key_raises_unavailable_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LlmUnavailable):
        llm.client()


def test_unavailable_is_not_an_llm_error() -> None:
    """둘을 갈라 둔다 — 키 없음은 고장이 아니다. 호출자가 문구를 달리 적는다."""
    assert not issubclass(llm.LlmUnavailable, llm.LlmError)


def test_client_is_built_with_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """60초를 넘기면 배치가 매달린다. 상위 워크플로에 시간 제한이 있다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    built: dict[str, Any] = {}

    def fake(**kwargs: Any) -> Any:
        built.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(anthropic, "Anthropic", fake)
    llm.client()
    assert built["timeout"] == llm.TIMEOUT
    assert built["api_key"] == "sk-ant-test"
