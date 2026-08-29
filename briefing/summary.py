"""LLM 요약의 입력 구성과 응답 검증 (F14·N13) — 순수 함수. LLM을 모른다.

**LLM은 압축만 한다.** 코드가 모은 사실을 한두 줄로 줄일 뿐, 해석·전망·권고를 내지 않는다.
그래서 입력에는 **제목·날짜·등급만** 넣고 본문은 넣지 않으며, 응답은 코드가 다시 검사한다.

검증(N13)에서 걸리면 **그 종목의 요약만 버린다** — 메일은 나가고 공시는 그대로 있다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from briefing.models import Briefing
from briefing.render import FORBIDDEN

MAX_LEN = 80
MAX_DISCLOSURES = 12  # 한 종목이 30건이면 입력이 커진다. 최근 것부터 자른다
SKIP_LEVELS = ("error", "unknown")  # 공시를 못 본 종목은 요약할 것이 없다

SYSTEM_PROMPT = """너는 한국 주식 공시를 한 줄로 요약한다.

규칙:
- **사실만 쓴다.** 해석·전망·권고·투자 판단을 절대 쓰지 않는다.
- **입력에 없는 사실을 만들지 않는다.** 공시 제목과 날짜에 있는 것만 쓴다.
- 종목당 한국어 한 문장, **80자 이내**.
- 등급(level)은 이미 정해져 있다. 바꾸거나 평가하지 않는다.
- 다음 표현을 쓰지 않는다: 추천 · 매수 · 매도 · 보류 · 호재 · 악재 · 목표가 · 손절 · 여력 · 이탈.
- 위험 유형이 없으면 무엇이 있었는지만 적는다.

좋은 예: "08/22 전환사채 400억 발행 결정, 08/11 최대주주 변경 — 최근 30일 위험 유형 2건"
나쁜 예: "오버행 부담으로 당분간 관망이 필요해 보인다"  (판단이다)"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["ticker", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _md(d: Any) -> str:
    return f"{d.month:02d}/{d.day:02d}"


def build_input(briefings: Sequence[Briefing]) -> list[dict[str, Any]]:
    """LLM에 보낼 입력 — 제목·날짜·등급만. 요약할 재료가 없는 종목은 뺀다."""
    out: list[dict[str, Any]] = []
    for b in briefings:
        if b.level in SKIP_LEVELS or (not b.disclosures and not b.news):
            continue
        item: dict[str, Any] = {
            "ticker": b.ticker,
            "name": b.name,
            "level": b.level,
            "disclosures": [
                {"date": _md(d.rcept_dt), "title": d.report_nm}
                for d in b.disclosures[:MAX_DISCLOSURES]
            ],
        }
        if b.news:
            item["news"] = [
                {"date": _md(n.published) if n.published else "", "title": n.title} for n in b.news
            ]
        if b.anomaly is not None:
            item["anomaly"] = {"score": b.anomaly.score, "verdict": b.anomaly.verdict}
        out.append(item)
    return out


def validate(
    payload: dict[str, Any], known_tickers: Sequence[str]
) -> tuple[dict[str, str], list[str]]:
    """응답을 검사해 통과한 것만 남긴다 (N13).

    Args:
        payload: `{"items": [{"ticker", "summary"}…]}`.
        known_tickers: 입력에 넣었던 티커. 그 밖의 티커는 지어낸 것이다.

    Returns:
        `({ticker: summary}, 버린 사유 목록)`.
    """
    known = set(known_tickers)
    kept: dict[str, str] = {}
    dropped: list[str] = []
    items = payload.get("items")
    if not isinstance(items, list):
        return {}, []
    for raw in items:
        if not isinstance(raw, dict):
            dropped.append("항목이 사전이 아님")
            continue
        ticker = str(raw.get("ticker", "")).strip()
        text = str(raw.get("summary", "")).strip()
        if not ticker:
            dropped.append("티커 없음")
        elif ticker not in known:
            dropped.append(f"{ticker}: 미지 티커 — 입력에 없다")
        elif not text:
            dropped.append(f"{ticker}: 빈 문자열")
        elif len(text) > MAX_LEN:
            dropped.append(f"{ticker}: 길이 {len(text)}자 > {MAX_LEN}")
        elif hit := next((w for w in FORBIDDEN if w in text), ""):
            dropped.append(f"{ticker}: 금지어 '{hit}'")
        else:
            kept[ticker] = text
    return kept, dropped
