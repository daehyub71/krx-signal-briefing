"""LLM 요약의 입력 구성과 응답 검증 (F14·N13) — 순수 함수. LLM을 모른다.

**LLM은 압축만 한다.** 코드가 모은 사실을 한두 줄로 줄일 뿐, 해석·전망·권고를 내지 않는다.
그래서 입력에는 **제목·날짜·등급만** 넣고 본문은 넣지 않으며, 응답은 코드가 다시 검사한다.

검증(N13)에서 걸리면 **그 종목의 요약만 버린다** — 메일은 나가고 공시는 그대로 있다.
"""

from __future__ import annotations

import re
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
- **위험 유형 건수를 적을 때는 입력의 `risk_count`를 그대로 쓴다.** 직접 세지 않는다.
  `risk_count`가 없으면 건수를 적지 않는다.
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


def _disclosure_item(d: Any, flag: str | None) -> dict[str, Any]:
    """공시 한 건. 걸린 것에는 등급을 붙인다 — 어느 것이 걸렸는지 모르면 짐작하게 된다."""
    item: dict[str, Any] = {"date": _md(d.rcept_dt), "title": d.report_nm}
    if flag:
        item["flag"] = flag
    return item


def build_input(briefings: Sequence[Briefing]) -> list[dict[str, Any]]:
    """LLM에 보낼 입력 — 제목·날짜·등급만. 요약할 재료가 없는 종목은 뺀다."""
    out: list[dict[str, Any]] = []
    for b in briefings:
        if b.level in SKIP_LEVELS or (not b.disclosures and not b.news):
            continue
        flag_levels = {f.rcept_no: f.level for f in b.flags}
        item: dict[str, Any] = {
            "ticker": b.ticker,
            "name": b.name,
            "level": b.level,
            "disclosures": [
                _disclosure_item(d, flag_levels.get(d.rcept_no))
                for d in b.disclosures[:MAX_DISCLOSURES]
            ],
        }
        # 건수를 세라고 시키지 않는다 — 세어서 준다.
        # 2026-08-30 첫 실호출에서 모델이 `level: "red"`만 보고 "위험 유형 2건"(실제 1건)을
        # 지어냈다. 사실이 입력에 없으면 짐작한다.
        if b.flags:
            item["risk_count"] = len(b.flags)
        if b.news:
            item["news"] = [
                {"date": _md(n.published) if n.published else "", "title": n.title} for n in b.news
            ]
        if b.anomaly is not None:
            item["anomaly"] = {"score": b.anomaly.score, "verdict": b.anomaly.verdict}
        out.append(item)
    return out


RISK_COUNT_RE = re.compile(r"위험\s*유형\s*(\d+)\s*건")


def _miscount(text: str, ticker: str, risk_counts: dict[str, int] | None) -> int | None:
    """요약이 적은 위험 유형 건수가 사실과 다르면 그 숫자를, 아니면 None."""
    if not risk_counts or ticker not in risk_counts:
        return None
    m = RISK_COUNT_RE.search(text)
    if m is None:
        return None
    said = int(m.group(1))
    return said if said != risk_counts[ticker] else None


def validate(
    payload: dict[str, Any],
    known_tickers: Sequence[str],
    risk_counts: dict[str, int] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """응답을 검사해 통과한 것만 남긴다 (N13).

    Args:
        payload: `{"items": [{"ticker", "summary"}…]}`.
        known_tickers: 입력에 넣었던 티커. 그 밖의 티커는 지어낸 것이다.
        risk_counts: `{ticker: 실제 플래그 수}`. 요약이 적은 건수와 다르면 버린다 —
            2026-08-30 실호출에서 1건을 "2건"이라 적은 일이 있었다. 지어낸 숫자는
            사실보다 더 그럴듯해 보여서 더 위험하다.

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
        elif (bad := _miscount(text, ticker, risk_counts)) is not None:
            real = (risk_counts or {})[ticker]
            dropped.append(f"{ticker}: 위험 유형 건수 {bad}건 — 실제 {real}건")
        else:
            kept[ticker] = text
    return kept, dropped
