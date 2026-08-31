"""전문 페이지를 Vercel에 올린다 (SPEC F20 v2 · D20 v2). I/O 층.

**배치가 정적 HTML을 만들어 올린다.** 브라우저가 DB에 붙지 않으므로 웹 번들에 키가
들어가지 않는다 — 상위 프로젝트에서 anon 키 범위가 문제가 된 적이 있다.

**있으면 좋은 층이다.** 배포가 실패해도 메일은 간다 — 링크 없이 발췌만 실린다 (F20).

## 왜 REST API인가

`vercel` CLI를 깔면 Node 런타임이 하나 더 필요하다. 배포할 것은 파일 두 개뿐이라
[Deployments API](https://vercel.com/docs/rest-api/endpoints/deployments)에 직접 올린다 —
파일 내용을 그대로 실어 보내면 끝이다.

## 무엇을 올리는가

| 경로 | 내용 |
|------|------|
| `/index.html` | 가장 최근 브리핑 |
| `/{YYYYMMDD}.html` | 그날의 브리핑 (메일 링크가 가리키는 곳) |

**이전 날짜는 남는다** — Vercel 배포는 매번 전체를 올리므로, 지난 것을 보존하려면
호출자가 함께 넘겨야 한다. v1은 그날치와 `index`만 올린다 (지난 브리핑은 DB에 있다).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from briefing import config

API = "https://api.vercel.com/v13/deployments"
TIMEOUT = 60.0
TOKEN_KEY = "VERCEL_TOKEN"
PROJECT_KEY = "VERCEL_PROJECT"


class DeployUnavailable(Exception):  # noqa: N818 — 고장이 아니다: 그 층이 오늘 없다
    """토큰·프로젝트가 없어 올릴 수 없다. 메일은 그대로 간다."""


class DeployError(Exception):
    """올리려 했으나 실패했다."""


def files_for(day: str, html: str) -> list[dict[str, str]]:
    """올릴 파일 목록. 그날치와 `index`를 같은 내용으로 올린다.

    Args:
        day: `YYYYMMDD`.
        html: 완성된 페이지.

    Returns:
        Vercel `files` 배열 — `{"file": 경로, "data": 내용}`.
    """
    return [
        {"file": f"{day}.html", "data": html},
        {"file": "index.html", "data": html},
    ]


def deploy(day: str, html: str, *, opener: Any = None) -> str:
    """페이지를 올리고 주소를 돌려준다 (F20).

    Args:
        day: `YYYYMMDD` — 메일 링크가 가리킬 경로.
        html: 완성된 페이지.
        opener: HTTP 실행기. 테스트가 대역을 넣는다.

    Returns:
        `https://…/{day}.html` 형태의 주소.

    Raises:
        DeployUnavailable: `VERCEL_TOKEN`·`VERCEL_PROJECT`가 없다.
        DeployError: 올리기 실패. **호출자가 삼킨다** — 메일은 링크 없이 간다.
    """
    token, project = config.optional(TOKEN_KEY), config.optional(PROJECT_KEY)
    if not token or not project:
        raise DeployUnavailable(f"{TOKEN_KEY} 또는 {PROJECT_KEY} 없음")
    payload = {
        "name": project,
        "project": project,
        "target": "production",
        "files": files_for(day, html),
        "projectSettings": {"framework": None},
    }
    request = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # 본문에 토큰이 실리지 않지만, 그래도 상태 코드만 남긴다 (N7).
        raise DeployError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeployError(f"{type(exc).__name__}") from None
    host = body.get("alias", [None])[0] or body.get("url")
    if not host:
        raise DeployError("응답에 주소가 없다")
    return f"https://{host}/{day}.html"
