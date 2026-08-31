"""deploy — 전문 페이지를 Vercel에 올린다 (SPEC F20 v2 · D20 v2). I/O 층.

**있으면 좋은 층이다.** 실패해도 메일은 간다 — 링크 없이 발췌만 실린다.
그 경계를 테스트가 지킨다.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from briefing import deploy

HTML = "<!doctype html><html><body>x</body></html>"


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def opener(body: dict[str, Any], sink: list[Any] | None = None) -> Any:
    def send(request: Any, timeout: float = 0) -> FakeResponse:
        if sink is not None:
            sink.append(request)
        return FakeResponse(body)

    return send


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(deploy.TOKEN_KEY, "tok")
    monkeypatch.setenv(deploy.PROJECT_KEY, "krx-signal-briefing")


# ── 올릴 것 ──────────────────────────────────────────────────────


def test_uploads_the_day_and_an_index() -> None:
    """메일 링크는 날짜 경로를 가리키고, 루트는 가장 최근 것을 보여 준다."""
    files = deploy.files_for("20260826", HTML)
    assert [f["file"] for f in files] == ["20260826.html", "index.html"]
    assert all(f["data"] == HTML for f in files)


def test_returns_the_dated_url() -> None:
    url = deploy.deploy("20260826", HTML, opener=opener({"alias": ["briefing.vercel.app"]}))
    assert url == "https://briefing.vercel.app/20260826.html"


def test_falls_back_to_the_deployment_url_when_there_is_no_alias() -> None:
    url = deploy.deploy("20260826", HTML, opener=opener({"url": "dep-abc.vercel.app"}))
    assert url == "https://dep-abc.vercel.app/20260826.html"


def test_sends_the_token_as_a_bearer_header() -> None:
    sink: list[Any] = []
    deploy.deploy("20260826", HTML, opener=opener({"url": "x"}, sink))
    (request,) = sink
    assert request.get_header("Authorization") == "Bearer tok"
    body = json.loads(request.data.decode())
    assert body["target"] == "production" and body["name"] == "krx-signal-briefing"
    assert len(body["files"]) == 2


# ── 없거나 실패하면 ──────────────────────────────────────────────


@pytest.mark.parametrize("missing", [deploy.TOKEN_KEY, deploy.PROJECT_KEY])
def test_missing_credentials_is_unavailable_not_an_error(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """키가 없는 것은 고장이 아니다 — 그 층이 오늘 없을 뿐이다."""
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(deploy.DeployUnavailable):
        deploy.deploy("20260826", HTML)


def test_unavailable_is_not_a_deploy_error() -> None:
    assert not issubclass(deploy.DeployUnavailable, deploy.DeployError)


def test_an_http_error_becomes_a_deploy_error() -> None:
    def boom(request: Any, timeout: float = 0) -> None:
        raise urllib.error.HTTPError("https://api.vercel.com", 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    with pytest.raises(deploy.DeployError, match="403"):
        deploy.deploy("20260826", HTML, opener=boom)


def test_a_network_failure_becomes_a_deploy_error() -> None:
    def boom(request: Any, timeout: float = 0) -> None:
        raise TimeoutError("느림")

    with pytest.raises(deploy.DeployError):
        deploy.deploy("20260826", HTML, opener=boom)


def test_a_response_without_an_address_is_an_error() -> None:
    with pytest.raises(deploy.DeployError):
        deploy.deploy("20260826", HTML, opener=opener({}))


def test_the_token_never_reaches_an_error_message() -> None:
    """토큰이 예외 메시지에 실리면 로그에 남는다 (N7)."""
    def boom(request: Any, timeout: float = 0) -> None:
        raise urllib.error.HTTPError("https://api.vercel.com?token=tok", 401, "no", {}, None)  # type: ignore[arg-type]

    with pytest.raises(deploy.DeployError) as caught:
        deploy.deploy("20260826", HTML, opener=boom)
    assert "tok" not in str(caught.value)
