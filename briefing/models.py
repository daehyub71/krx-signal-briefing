"""도메인 모델.

이 모듈은 LangGraph·DB·HTTP를 모른다. 그래프 층을 걷어내도 그대로 살아남아야 한다 (SPEC N3).

두 계약을 여기서 고정한다 (PLAN §4):
- **읽는 쪽** `SignalRow` — `ksa_signals.evidence` (상위 프로젝트 공유 계약).
  키가 없어도 죽지 않는다 (R8).
- **쓰는 쪽** `Briefing.to_row()` · `RunRecord.to_row()` — `ksb_briefings` · `ksb_runs` 열과 1:1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, get_args

Level = Literal["red", "amber", "none", "unknown", "error"]
FlagLevel = Literal["red", "amber"]
RunStatus = Literal[
    "ok", "no_signals", "gate_timeout", "dart_partial", "dart_failed", "send_failed"
]

# schema.sql의 CHECK 제약과 같은 값이어야 한다. 코드가 놓쳐도 DB가 2차 방어선이 된다.
LEVELS: tuple[Level, ...] = get_args(Level)
RUN_STATUSES: tuple[RunStatus, ...] = get_args(RunStatus)

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

# 공시 조회 창. Briefing.window_days의 기본값이자 F4의 bgn_de 계산 기준.
WINDOW_DAYS = 30


def dart_link(rcept_no: str) -> str:
    """접수번호 → DART 원문 뷰어 링크 (SPEC N2 — 모든 공시 항목에 필수)."""
    return f"{DART_VIEWER}{rcept_no}"


# ── 읽는 쪽 — ksa_signals ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SignalRow:
    """`ksa_signals` 한 행 중 브리핑이 쓰는 것.

    `evidence`는 상위 프로젝트의 공유 계약이다. 키가 없으면 빈 값을 돌려준다 —
    상위가 키를 바꿔도 메일 전체를 죽이지 않는다 (SPEC R8).
    """

    d: date
    strategy: str
    ticker: str
    name: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def conditions(self) -> tuple[tuple[str, bool, str], ...]:
        """(label, ok, actual) 순서대로. 상위 메일과 같은 순서로 렌더한다."""
        raw = self.evidence.get("conditions") or []
        return tuple(
            (str(c.get("label", "")), bool(c.get("ok", False)), str(c.get("actual", "")))
            for c in raw
            if isinstance(c, dict)
        )

    @property
    def close(self) -> int:
        """종가(원). 없으면 0."""
        return int((self.evidence.get("price") or {}).get("close", 0) or 0)

    @property
    def change_pct(self) -> float:
        """등락률(%). 없으면 0.0."""
        return float((self.evidence.get("price") or {}).get("change_pct", 0.0) or 0.0)

    @property
    def in_progress(self) -> bool:
        """진행 중인 주봉 기준 판정인가 (상위 F8 표기)."""
        return bool((self.evidence.get("meta") or {}).get("in_progress", False))


# ── 쓰는 쪽 — ksb_briefings ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Disclosure:
    """공시 하나. OpenDART `list.json` 한 항목에 대응한다."""

    rcept_dt: date
    report_nm: str
    rcept_no: str
    flr_nm: str = ""
    corrected: bool = False  # `[정정]`·`[기재정정]` 접두가 있었는가

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태. date는 ISO 문자열로 — supabase-py가 date를 직렬화하지 못한다."""
        return {
            "rcept_dt": self.rcept_dt.isoformat(),
            "report_nm": self.report_nm,
            "rcept_no": self.rcept_no,
            "flr_nm": self.flr_nm,
            "corrected": self.corrected,
        }


@dataclass(frozen=True, slots=True)
class Flag:
    """등급을 올린 공시 하나 — "몇 점"이 아니라 "어떤 공시 때문인지"를 남긴다 (SPEC D5)."""

    rule: str
    level: FlagLevel
    rcept_no: str
    report_nm: str

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태."""
        return {
            "rule": self.rule,
            "level": self.level,
            "rcept_no": self.rcept_no,
            "report_nm": self.report_nm,
        }


@dataclass(frozen=True, slots=True)
class Briefing:
    """신호 한 건에 대한 브리핑. `ksb_briefings` 한 행.

    프로즌이다. `summary`·`error`는 뒤 단계가 `dataclasses.replace()`로 갈아끼운다 —
    노드가 값을 슬쩍 바꾸지 못하게 하기 위해서다.
    """

    d: date
    strategy: str
    ticker: str
    name: str
    corp_code: str | None
    level: Level
    flags: tuple[Flag, ...] = ()
    disclosures: tuple[Disclosure, ...] = ()
    window_days: int = WINDOW_DAYS
    summary: str | None = None
    error: str = ""  # level == 'error'일 때 원인. 열이 아니라 ksb_runs.detail로 간다

    @classmethod
    def from_signal(
        cls,
        signal: SignalRow,
        corp_code: str | None,
        level: Level,
        *,
        flags: tuple[Flag, ...] = (),
        disclosures: tuple[Disclosure, ...] = (),
        error: str = "",
    ) -> Briefing:
        """신호 행에서 브리핑을 만든다 — 키·이름은 신호에서 그대로 온다."""
        return cls(
            d=signal.d,
            strategy=signal.strategy,
            ticker=signal.ticker,
            name=signal.name,
            corp_code=corp_code,
            level=level,
            flags=flags,
            disclosures=disclosures,
            error=error,
        )

    def link(self, rcept_no: str) -> str:
        """공시 원문 링크."""
        return dart_link(rcept_no)

    def to_row(self) -> dict[str, Any]:
        """`ksb_briefings` upsert 행 (F9). 열 이름이 배치와 DB의 계약이다."""
        return {
            "d": self.d.isoformat(),
            "strategy": self.strategy,
            "ticker": self.ticker,
            "name": self.name,
            "corp_code": self.corp_code,
            "level": self.level,
            "flags": [f.to_json() for f in self.flags],
            "disclosures": [x.to_json() for x in self.disclosures],
            "window_days": self.window_days,
            "summary": self.summary,
        }


# ── 실행 결과 ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SendResult:
    """발송 결과. 발송 노드는 예외를 밖으로 내지 않고 이 값을 상태에 적는다 (SPEC N5·N11)."""

    ok: bool
    sent_n: int = 0
    error: str = ""
    channel: str = "email"


@dataclass(slots=True)
class RunRecord:
    """`ksb_runs` 한 행. 안 온 게 정상인지 고장인지를 사후에 가리는 기록이다."""

    data_date: date | None
    status: RunStatus
    signal_n: int = 0
    red_n: int = 0
    amber_n: int = 0
    error_n: int = 0
    dart_calls: int = 0
    summary_n: int = 0
    llm_tokens: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        """`ksb_runs` insert 행."""
        return {
            "data_date": self.data_date.isoformat() if self.data_date else None,
            "signal_n": self.signal_n,
            "red_n": self.red_n,
            "amber_n": self.amber_n,
            "error_n": self.error_n,
            "dart_calls": self.dart_calls,
            "summary_n": self.summary_n,
            "llm_tokens": self.llm_tokens,
            "status": self.status,
            "detail": self.detail,
        }
