"""OpenDART HTTP 클라이언트 (F3·F4). 표준 라이브러리 `urllib`만 쓴다 (N4).

**키는 URL 쿼리에 실린다.** 예외 메시지·로그에 URL이 통째로 들어가기 쉬우므로
밖으로 나가는 모든 문자열을 `mask()`로 거른다 (N7).

| 상태 | 뜻 | 처리 |
|------|-----|------|
| `000` | 정상 | 항목 파싱 |
| `013` | 조회 결과 없음 | **공시 0건 — 오류 아님** |
| `020` | 요청 한도 초과 | 1회 재시도 → `DartRateLimitError` |
| `800` | 시스템 점검 | 1회 재시도 → `DartMaintenanceError` |
| `010` `011` 등 | 키 오류 등 | 재시도 없이 `DartError` — 다시 불러도 같다 |
| HTTP 5xx · 타임아웃 · 연결 오류 | 일시 장애 | 1회 재시도 → `DartError` |

파싱 실패·오류 본문 판별은 순수 모듈(`corp.py`)에 있다. 여기는 바이트를 받아 오는 일만 한다.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from briefing import config
from briefing.models import Disclosure

BASE = "https://opendart.fss.or.kr/api"
TIMEOUT = 20.0
PAGE_COUNT = 100
RETRY_WAIT = 2.0  # 1회 재시도 전 대기(초). 020이면 잠깐 쉬는 게 맞다

STATUS_OK = "000"
STATUS_NO_DATA = "013"
STATUS_RATE_LIMIT = "020"
STATUS_MAINTENANCE = "800"
RETRYABLE = (STATUS_RATE_LIMIT, STATUS_MAINTENANCE)


class DartError(RuntimeError):
    """OpenDART 호출 실패. 메시지에 키가 없다."""

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class DartRateLimitError(DartError):
    """`020` — 일 한도(20,000) 초과."""


class DartMaintenanceError(DartError):
    """`800` — 시스템 점검. HTTP 200으로 온다 (2026-08-29 실측)."""


def mask(text: str, key: str) -> str:
    """문자열에서 키를 `***`로 가린다."""
    return text.replace(key, "***") if key else text


def _key() -> str:
    return config.require("DART_API_KEY")


def _get(path: str, params: dict[str, str], key: str) -> bytes:
    """GET 1회. 네트워크 오류는 키를 가린 `DartError`로 바꾼다."""
    url = f"{BASE}/{path}?" + urllib.parse.urlencode({"crtfc_key": key, **params})
    try:
        with urlopen(Request(url), timeout=TIMEOUT) as resp:
            return bytes(resp.read())
    except HTTPError as exc:
        raise DartError(f"{path} HTTP {exc.code} {mask(str(exc.reason), key)}") from None
    except URLError as exc:
        raise DartError(f"{path} 연결 실패: {mask(str(exc.reason), key)}") from None
    except OSError as exc:  # socket.timeout 등
        raise DartError(f"{path} {mask(str(exc), key)}") from None


def _get_with_retry(path: str, params: dict[str, str], key: str) -> bytes:
    """일시 장애(네트워크·5xx·020·800)는 1회만 재시도한다."""
    try:
        data = _get(path, params, key)
    except DartError as exc:
        print(f"[dart] {exc} — {RETRY_WAIT}초 후 재시도")
        sleep(RETRY_WAIT)
        return _get(path, params, key)
    if path == "list.json" and _status_of(data) in RETRYABLE:
        print(f"[dart] status={_status_of(data)} — {RETRY_WAIT}초 후 재시도")
        sleep(RETRY_WAIT)
        return _get(path, params, key)
    return data


def _status_of(data: bytes) -> str:
    try:
        return str(json.loads(data).get("status", ""))
    except ValueError:
        return ""


def fetch_corp_codes() -> bytes:
    """`corpCode.xml` 응답 바이트 (zip). 파싱·오류 본문 판별은 `corp.parse_corp_codes()`."""
    return _get_with_retry("corpCode.xml", {}, _key())


def fetch_disclosures(corp_code: str, bgn: date, end: date) -> list[Disclosure]:
    """한 회사의 기간 내 공시 목록 (F4). `013`이면 빈 목록.

    Args:
        corp_code: DART 고유번호 8자리.
        bgn: 조회 시작일.
        end: 조회 종료일.

    Returns:
        응답 순서 그대로 (DART는 최신순). 100건을 넘으면 로그로 알리고 100건만 돌려준다.

    Raises:
        DartRateLimitError: `020` (1회 재시도 후).
        DartMaintenanceError: `800` (1회 재시도 후).
        DartError: 그 밖의 오류 상태·HTTP 오류·네트워크 오류. 메시지에 키가 없다.
    """
    key = _key()
    params = {
        "corp_code": corp_code,
        "bgn_de": bgn.strftime("%Y%m%d"),
        "end_de": end.strftime("%Y%m%d"),
        "page_count": str(PAGE_COUNT),
    }
    data = _get_with_retry("list.json", params, key)
    payload: dict[str, Any] = json.loads(data)
    status = str(payload.get("status", ""))
    message = mask(str(payload.get("message", "")), key)

    if status == STATUS_NO_DATA:
        return []
    if status == STATUS_RATE_LIMIT:
        raise DartRateLimitError(f"list.json status=020 한도 초과: {message}", status)
    if status == STATUS_MAINTENANCE:
        raise DartMaintenanceError(f"list.json status=800 점검 중: {message}", status)
    if status != STATUS_OK:
        raise DartError(f"list.json status={status}: {message}", status)

    total = int(payload.get("total_count", 0) or 0)
    if total > PAGE_COUNT:
        print(f"[dart] {corp_code} 공시 {total}건 — {PAGE_COUNT}건만 가져왔다")
    # 매핑은 models에 한 곳 — MCP 경로(dart_mcp.py)와 같은 함수를 쓴다
    return [Disclosure.from_dart_item(x) for x in payload.get("list", [])]
