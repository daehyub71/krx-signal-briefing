"""LLM 분석의 입력 구성과 응답 검증 (SPEC F19·N13 v2, v3.0) — 순수 함수. LLM을 모른다.

**LLM은 판정을 설명할 뿐 바꾸지 않는다.** 판정(`정합`/`불일치`/`무관`)과 점수는
`verdict.py`가 규칙으로 낸다 (F18). 모델에 숫자를 물으면 지어낸다 — 2026-08-30에
플래그 1건인 종목의 요약이 "위험 유형 2건"이라고 적었다.

## v2.0에서 무엇이 달라졌나

| | v2.0 (`summary.py`) | v3.0 (`analysis.py`) |
|---|---|---|
| 하는 일 | 공시 제목을 80자로 **압축** | 세 갈래 증거로 신호를 **검증한 근거 서술** |
| 입력 | 제목·날짜·등급 | + **공시 본문**(오버행·자금용도) · **수급 30일** · 코드가 낸 판정·점수 |
| 출력 | 80자 | 종목당 **최대 2,000자** |

## 2,000자는 상한이지 목표가 아니다 (R21)

정형 공시뿐인 종목은 쓸 사실이 200자도 안 된다. 상한을 목표로 오해하면 채우려고
지어낸다 — 건수를 날조한 것과 같은 실패다. 프롬프트에 그렇게 박고,
`validate()`가 입력에 없는 숫자를 대조한다.

검증에서 걸리면 **그 종목의 서술만 버린다** — 판정·점수·공시·뉴스·수급은 그대로 나간다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from briefing.models import Briefing
from briefing.render import has_forbidden
from briefing.verdict import STANDS, Verdict

MAX_LEN = 2000  # 종목당 상한 (F19·D19). **목표가 아니다** (R21)
MAX_DISCLOSURES = 12  # 한 종목이 30건이면 입력이 커진다. 최근 것부터 자른다
MAX_NEWS = 5
MAX_FLOW_DAYS = 10  # 수급은 최근 며칠만 넣는다 — 30일 전부는 토큰만 먹는다
SKIP_LEVELS = ("error", "unknown")  # 공시를 못 본 종목은 검증할 것이 없다

SYSTEM_PROMPT = """너는 한국 주식의 차트 신호가 근거를 갖는지 검증한다.

입력은 종목마다 이렇게 온다:
- signal: 상위 배치가 낸 차트 신호와 그 조건
- disclosures / bodies: 최근 공시 제목과, 위험 유형에 걸린 공시의 본문
- news: 같은 기간 뉴스 제목과 기사 요약
- flows: 기관·외국인·개인 순매수(원). 음수는 순매도다
- verdict: **코드가 규칙으로 낸 판정과 점수, 그리고 그 근거 조각**

네가 할 일은 verdict를 **설명**하는 것이다. 세 갈래(공시·뉴스·수급)가 차트 신호를
받치는지 거스르는지, 무엇을 근거로 그렇게 보는지 쓴다.

규칙:
- **verdict의 판정과 점수를 바꾸지 않는다.** 다른 결론을 내지 않는다. 너는 설명한다.
- **입력에 없는 사실을 만들지 않는다.** 숫자는 입력에 있는 것만 쓴다.
- **2,000자는 상한이지 목표가 아니다.** 쓸 사실이 200자면 200자만 쓴다.
  재료가 얇은데 길게 쓰려고 하면 지어내게 된다. 짧은 것이 낫다.
- 한국어. 사실과 그 사실이 신호에 대해 뜻하는 바까지 쓴다.
- **매매 판단을 쓰지 않는다.** 다음 표현을 쓰지 않는다:
  추천 · 매수 · 매도 · 보류 · 목표가 · 손절 · 여력 · 이탈 · 진입 · 비중.
  "언제 사라/팔라"는 이 메일이 하지 않는 일이다.

좋은 예:
"08/26 전환사채 100억 발행 결정. 자금은 전액 제2공장 시설투자로, 뉴스도 같은 내용이다.
다만 전환 시 발행주식의 5.10%가 늘고 사모라 1년간 전환이 막힌다. 공시 당일 외국인이
11.4억을 순매도하고 개인이 그만큼 받았다 — 정배열 전환 신호를 수급이 받치지 않는다."

나쁜 예:
"오버행 부담이 크므로 당분간 관망이 필요하다"  (매매 판단이다)
"실적 개선세가 뚜렷하다"  (입력에 없는 사실이다)"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

# 서술이 적은 숫자를 사실과 대조한다 (N13 v2).
RISK_COUNT_RE = re.compile(r"위험\s*유형\s*(\d+)\s*건")
OVERHANG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _md(d: Any) -> str:
    return f"{d.month:02d}/{d.day:02d}"


def _eok(won: int | None) -> float | None:
    """원 → 억. 입력에 큰 숫자를 그대로 주면 모델이 자릿수를 흘린다."""
    return None if won is None else round(won / 100_000_000, 1)


def build_input(
    briefings: Sequence[Briefing], verdicts: dict[str, Verdict]
) -> list[dict[str, Any]]:
    """LLM에 보낼 입력 (F19). 검증할 재료가 없는 종목은 뺀다.

    Args:
        briefings: 공시·본문·뉴스·수급이 채워진 브리핑.
        verdicts: `{ticker: Verdict}` — 코드가 낸 판정·점수.

    Returns:
        종목별 입력. 공시도 뉴스도 없는 종목과 조회 실패 종목은 빠진다.
    """
    out: list[dict[str, Any]] = []
    for b in briefings:
        if b.level in SKIP_LEVELS or (not b.disclosures and not b.news):
            continue
        v = verdicts.get(b.ticker)
        flagged = {f.rcept_no for f in b.flags}
        item: dict[str, Any] = {
            "ticker": b.ticker,
            "name": b.name,
            "level": b.level,
            "signal": {
                "strategy": b.strategy,
                "conditions": [
                    {"label": label, "ok": ok, "actual": actual}
                    for label, ok, actual in b.conditions
                ],
            },
            "disclosures": [
                {
                    "date": _md(d.rcept_dt),
                    "title": d.report_nm,
                    **({"flag": True} if d.rcept_no in flagged else {}),
                }
                for d in b.disclosures[:MAX_DISCLOSURES]
            ],
        }
        if b.flags:
            item["risk_count"] = len(b.flags)
        if b.bodies:
            item["bodies"] = [
                {
                    "amount_eok": _eok(x.amount),
                    "use_of_funds": [[label, _eok(won)] for label, won in x.use_of_funds],
                    "method": x.method,
                    "coupon_rate": x.coupon_rate,
                    "conv_price": x.conv_price,
                    "overhang_pct": x.overhang_pct,
                    "outstanding_eok": _eok(x.outstanding),
                    "refix_floor": x.refix_floor,
                }
                for x in x_sorted(b)
            ]
        if b.news:
            item["news"] = [
                {
                    "date": _md(n.published) if n.published else "",
                    "title": n.title,
                    "summary": n.summary,
                }
                for n in b.news[:MAX_NEWS]
            ]
        if b.flows is not None and b.flows.days:
            item["flows"] = {
                "unit": "억원",
                "total_30d": {
                    "inst": _eok(b.flows.inst_total),
                    "foreign": _eok(b.flows.foreign_total),
                    "indiv": _eok(b.flows.indiv_total),
                },
                "recent": [
                    {
                        "date": _md(x.d),
                        "inst": _eok(x.inst),
                        "foreign": _eok(x.foreign),
                        "indiv": _eok(x.indiv),
                    }
                    for x in b.flows.recent(MAX_FLOW_DAYS).days
                ],
            }
        if b.anomaly is not None:
            item["anomaly"] = {"score": b.anomaly.score, "verdict": b.anomaly.verdict}
        if v is not None:
            item["verdict"] = {
                "stand": v.stand,
                "score": v.score,
                "parts": [[p.label, p.delta] for p in v.parts],
            }
        out.append(item)
    return out


def x_sorted(b: Briefing) -> list[Any]:
    """본문을 오버행 큰 순으로. 여러 건이면 큰 것을 먼저 읽게 한다."""
    return sorted(b.bodies, key=lambda x: -(x.overhang_pct or 0.0))


def _miscount(text: str, ticker: str, risk_counts: dict[str, int] | None) -> int | None:
    """서술이 적은 위험 유형 건수가 사실과 다르면 그 숫자를, 아니면 None."""
    if not risk_counts or ticker not in risk_counts:
        return None
    m = RISK_COUNT_RE.search(text)
    if m is None:
        return None
    said = int(m.group(1))
    return said if said != risk_counts[ticker] else None


def _bad_overhang(text: str, ticker: str, overhangs: dict[str, set[float]] | None) -> str | None:
    """서술이 적은 `N%`가 입력의 오버행과 다르면 그 숫자를 돌려준다.

    퍼센트는 오버행 말고도 등락률·지분율 등에 쓰인다. 그래서 **`오버행`·`전환` 근처의
    퍼센트만** 본다 — 아무 `%`나 잡으면 멀쩡한 서술을 버린다.
    """
    if not overhangs or ticker not in overhangs or not overhangs[ticker]:
        return None
    for m in re.finditer(r"[^.。\n]*?(\d+(?:\.\d+)?)\s*%[^.。\n]*", text):
        clause = m.group(0)
        if "오버행" not in clause and "전환" not in clause and "희석" not in clause:
            continue
        said = float(m.group(1))
        if not any(abs(said - v) < 0.05 for v in overhangs[ticker]):
            return m.group(1)
    return None


def validate(
    payload: dict[str, Any],
    known_tickers: Sequence[str],
    *,
    stands: dict[str, str] | None = None,
    risk_counts: dict[str, int] | None = None,
    overhangs: dict[str, set[float]] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """응답을 검사해 통과한 것만 남긴다 (N13 v2).

    걸린 항목만 버린다 — 판정·점수·공시·뉴스·수급은 그대로 나간다.

    Args:
        payload: `{"items": [{"ticker", "reason"}…]}`.
        known_tickers: 입력에 넣었던 티커. 그 밖의 티커는 지어낸 것이다.
        stands: `{ticker: 코드가 낸 판정}`. 서술이 **다른 판정 단어**를 쓰면 버린다 —
            LLM은 설명만 하고 결론을 바꾸지 못한다 (F18).
        risk_counts: `{ticker: 실제 플래그 수}`. 2026-08-30에 1건을 "2건"이라 적은 일이 있다.
        overhangs: `{ticker: 입력에 있던 오버행 비율들}`.

    Returns:
        `({ticker: reason}, 버린 사유 목록)`.
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
        text = str(raw.get("reason", "")).strip()
        if not ticker:
            dropped.append("티커 없음")
        elif ticker not in known:
            dropped.append(f"{ticker}: 미지 티커 — 입력에 없다")
        elif not text:
            dropped.append(f"{ticker}: 빈 문자열")
        elif len(text) > MAX_LEN:
            dropped.append(f"{ticker}: 길이 {len(text)}자 > {MAX_LEN}")
        elif hit := has_forbidden(text):
            dropped.append(f"{ticker}: 금지어 '{hit}'")
        elif bad_stand := _wrong_stand(text, ticker, stands):
            dropped.append(f"{ticker}: 판정을 '{bad_stand}'로 바꿔 씀 — 코드 판정과 다르다")
        elif (bad := _miscount(text, ticker, risk_counts)) is not None:
            real = (risk_counts or {})[ticker]
            dropped.append(f"{ticker}: 위험 유형 건수 {bad}건 — 실제 {real}건")
        elif pct := _bad_overhang(text, ticker, overhangs):
            dropped.append(f"{ticker}: 입력에 없는 비율 {pct}%")
        else:
            kept[ticker] = text
    return kept, dropped


def _wrong_stand(text: str, ticker: str, stands: dict[str, str] | None) -> str | None:
    """서술이 코드 판정과 **다른** 판정 단어를 쓰면 그 단어를 돌려준다.

    코드 판정을 그대로 쓰는 것은 좋다. 다른 것을 쓰면 결론을 바꾼 것이다 (F18).
    """
    if not stands or ticker not in stands:
        return None
    mine = stands[ticker]
    return next((s for s in STANDS if s != mine and s in text), None)
