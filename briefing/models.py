"""도메인 모델.

이 모듈은 LangGraph·DB·HTTP를 모른다. 그래프 층을 걷어내도 그대로 살아남아야 한다 (SPEC N3).

두 계약을 여기서 고정한다 (PLAN §4):
- **읽는 쪽** `SignalRow` — `ksa_signals.evidence` (상위 프로젝트 공유 계약).
  키가 없어도 죽지 않는다 (R8).
- **쓰는 쪽** `Briefing.to_row()` · `RunRecord.to_row()` — `ksb_briefings` · `ksb_runs` 열과 1:1.
"""

from __future__ import annotations

from collections.abc import Iterable
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


def _as_int(v: Any) -> int:
    """숫자로 읽히면 int, 아니면 0 (R8). `int("8,420")`은 예외를 던진다."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(v: Any) -> float:
    """숫자로 읽히면 float, 아니면 0.0 (R8)."""
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── 읽는 쪽 — ksa_signals ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SignalRow:
    """`ksa_signals` 한 행 중 브리핑이 쓰는 것.

    `evidence`는 상위 프로젝트의 공유 계약이다 (상위 PLAN §4 — 우리는 세 번째 소비자).
    **상위가 키를 바꾸거나 값 모양을 바꿔도 메일 전체가 죽으면 안 된다** (SPEC R8):
    없는 키는 빈 값을 돌려주고, 숫자가 아닌 값은 0으로 떨어진다. 그 줄만 비고 공시는 그대로 나간다.

    실제로 있었던 모양들: `evidence`가 통째로 `null` · 종가가 `"8,420"`(쉼표 낀 문자열) ·
    `conditions`가 목록이 아닌 문자열 · 조건 항목에 `label`이 없음.
    """

    d: date
    strategy: str
    ticker: str
    name: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def ev(self) -> dict[str, Any]:
        """`evidence`를 딕셔너리로 본다. DB가 `null`을 주는 날이 있다 (R8)."""
        return self.evidence if isinstance(self.evidence, dict) else {}

    @property
    def conditions(self) -> tuple[tuple[str, bool, str], ...]:
        """(label, ok, actual) 순서대로. 상위 메일과 같은 순서로 렌더한다.

        목록이 아니면 빈 튜플. 항목에 키가 없으면 **그 자리만** 빈 문자열이다.
        """
        raw = self.ev.get("conditions")
        if not isinstance(raw, list):
            return ()
        return tuple(
            (str(c.get("label", "")), bool(c.get("ok", False)), str(c.get("actual", "")))
            for c in raw
            if isinstance(c, dict)
        )

    @property
    def _price(self) -> dict[str, Any]:
        p = self.ev.get("price")
        return p if isinstance(p, dict) else {}

    @property
    def close(self) -> int:
        """종가(원). 없거나 숫자로 읽히지 않으면 0 — 그 줄만 빈다 (R8)."""
        return _as_int(self._price.get("close"))

    @property
    def change_pct(self) -> float:
        """등락률(%). 없거나 숫자로 읽히지 않으면 0.0 (R8)."""
        return _as_float(self._price.get("change_pct"))

    @property
    def in_progress(self) -> bool:
        """진행 중인 주봉 기준 판정인가 (상위 F8 표기)."""
        meta = self.ev.get("meta")
        return bool(meta.get("in_progress", False)) if isinstance(meta, dict) else False


# ── 쓰는 쪽 — ksb_briefings ──────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Disclosure:
    """공시 하나. OpenDART `list.json` 한 항목에 대응한다."""

    rcept_dt: date
    report_nm: str
    rcept_no: str
    flr_nm: str = ""
    corrected: bool = False  # `[정정]`·`[기재정정]` 접두가 있었는가

    @classmethod
    def from_dart_item(cls, item: dict[str, Any]) -> Disclosure:
        """OpenDART `list.json` 항목 → Disclosure.

        REST(`dart.py`)와 MCP(`dart_mcp.py`)가 **같은 매핑**을 쓴다.

        Args:
            item: `rcept_dt`(YYYYMMDD) · `report_nm` · `rcept_no` · `flr_nm` 키를 가진 사전.
        """
        raw = str(item["rcept_dt"]).replace("-", "")
        return cls(
            rcept_dt=date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])),
            report_nm=str(item.get("report_nm", "")).strip(),
            rcept_no=str(item["rcept_no"]),
            flr_nm=str(item.get("flr_nm", "")).strip(),
        )

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
class Anomaly:
    """korean-dart-mcp `disclosure_anomaly` — 보조 신호 (F4b). **등급을 바꾸지 않는다.**"""

    score: int  # 0~100
    verdict: str  # clean / watch / warning / red_flag
    summary: str = ""
    flags: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태."""
        return {
            "score": self.score,
            "verdict": self.verdict,
            "summary": self.summary,
            "flags": list(self.flags),
        }


@dataclass(frozen=True, slots=True)
class Insider:
    """korean-dart-mcp `insider_signal` — 임원·주요주주 매매 군집 (F4b)."""

    signal: str  # strong_sell_cluster / sell_cluster / buy_cluster / none …
    buy_events: int = 0
    sell_events: int = 0
    unique_buyers: int = 0
    unique_sellers: int = 0
    net_change_shares: int = 0
    summary: str = ""

    @property
    def sell_cluster(self) -> bool:
        """매도 군집인가 — 🟡 `insider_sell_cluster` 규칙의 입력."""
        return "sell_cluster" in self.signal

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태."""
        return {
            "signal": self.signal,
            "buy_events": self.buy_events,
            "sell_events": self.sell_events,
            "unique_buyers": self.unique_buyers,
            "unique_sellers": self.unique_sellers,
            "net_change_shares": self.net_change_shares,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class NewsItem:
    """뉴스 한 건 (F11). 제목·언론사 링크·날짜만 — 본문은 담지 않는다.

    제목은 정제된 상태로 들어온다 (`news_mcp.clean_text` — `<b>` 태그·HTML 엔티티 제거).
    """

    title: str
    link: str  # 네이버 뉴스 링크
    origin: str = ""  # 원문(언론사) 링크
    published: date | None = None
    summary: str = ""  # 기사 요약 (네이버 `description`, ~100자) — F11 v2, v3.0

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태."""
        return {
            "title": self.title,
            "link": self.link,
            "origin": self.origin,
            "published": self.published.isoformat() if self.published else None,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class Flow:
    """korea-stock-mcp `get_stock_trade_info` — 시세 참고 (F12·D14). 순매수는 없다."""

    bas_dd: str  # 마지막 거래일 YYYYMMDD
    close: int
    mktcap: int  # 시가총액(원)
    list_shrs: int  # 상장주식수
    trdval_5d: int  # 최근 ≤5거래일 거래대금 합(원)
    days: int  # 합산에 든 거래일 수

    def display(self) -> str:
        """본문 한 줄 — 사실만. 억 단위 반올림."""
        eok = 100_000_000
        md = f"{self.bas_dd[4:6]}/{self.bas_dd[6:8]}"
        cap, val = self.mktcap // eok, self.trdval_5d // eok
        return f"시총 {cap:,}억 · {self.days}일 거래대금 {val:,}억 ({md})"

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태."""
        return {
            "bas_dd": self.bas_dd,
            "close": self.close,
            "mktcap": self.mktcap,
            "list_shrs": self.list_shrs,
            "trdval_5d": self.trdval_5d,
            "days": self.days,
        }


@dataclass(frozen=True, slots=True)
class FlowDay:
    """하루치 투자자별 순매수거래대금(원) — 상위 `ksc_investor_flows` 한 행 (SPEC F17)."""

    d: date
    inst: int | None = None  # 기관합계
    foreign: int | None = None  # 외국인합계 = 외국인 + 기타외국인 (상위는 따로 담는다)
    indiv: int | None = None  # 개인

    def to_json(self) -> dict[str, Any]:
        return {
            "d": self.d.isoformat(),
            "inst": self.inst,
            "foreign": self.foreign,
            "indiv": self.indiv,
        }


@dataclass(frozen=True, slots=True)
class InvestorFlows:
    """종목 하나의 수급 30일 (SPEC F17, v3.0). 날짜 **오름차순**.

    누가 사고 팔았는지가 세 갈래 증거의 셋째다. 씨피시스템 CB 공시일에 외국인이
    11.3억을 팔고 개인이 11.3억을 샀다 — 공시와 뉴스만으로는 보이지 않는 사실이다.

    합계는 **`None`을 0으로 세지 않는다.** 그 투자자 표에 종목이 없던 날과
    순매수가 0원이던 날은 다르다.
    """

    days: tuple[FlowDay, ...] = ()

    @staticmethod
    def _sum(values: Iterable[int | None]) -> int | None:
        got = [v for v in values if v is not None]
        return sum(got) if got else None

    @property
    def inst_total(self) -> int | None:
        """기간 누적 기관 순매수(원). 값이 하나도 없으면 None."""
        return self._sum(x.inst for x in self.days)

    @property
    def foreign_total(self) -> int | None:
        return self._sum(x.foreign for x in self.days)

    @property
    def indiv_total(self) -> int | None:
        return self._sum(x.indiv for x in self.days)

    def on(self, day: date) -> FlowDay | None:
        """그날의 수급. **공시일 당일**을 보려고 있다."""
        return next((x for x in self.days if x.d == day), None)

    def recent(self, n: int = 5) -> InvestorFlows:
        """최근 n거래일만."""
        return InvestorFlows(days=self.days[-n:] if n > 0 else ())

    def to_json(self) -> list[dict[str, Any]]:
        return [x.to_json() for x in self.days]


@dataclass(frozen=True, slots=True)
class EventBody:
    """플래그된 공시의 **본문** (SPEC F15, v3.0).

    `report_nm` 한 줄로는 무슨 일인지 알 수 없다. korean-dart-mcp `get_corporate_event`가
    주는 구조화 본문을 여기에 담는다. 값이 없으면 `None` — 사채가 아닌 사건에는
    전환가·오버행이 없다.

    같은 공시가 이렇게 달라진다 (2026-08-26 실측):

    | | 씨피시스템 | 엔투텍 |
    |---|---|---|
    | 제목 | `주요사항보고서(전환사채권발행결정)` | 같은 제목 |
    | 금액 | 100억 | 120억 |
    | 자금용도 | 시설자금 전액 | 타법인 증권 취득 |
    | 이자 | 0.0% / 0.0% | 4% / 4% |
    | **오버행** | **5.10%** | **18.63%** |
    | 미상환 잔액 | 234억 | **4,891억** |

    오버행 비율(`overhang_pct`)이 이 모델의 핵심이다. 잠재 물량이 발행주식의 5%인지
    19%인지는 같은 "전환사채 발행" 안에서 전혀 다른 사실이다.
    """

    rcept_no: str
    event_type: str  # cb_issuance · bw_issuance · rights_offering …
    decided_on: str = ""  # 이사회 결의일 (원문 표기 그대로)
    amount: int | None = None  # 발행·조달 금액(원)
    use_of_funds: tuple[tuple[str, int], ...] = ()  # (용도, 금액) — 비어 있으면 미기재
    kind: str = ""  # 사채의 종류 (`무보증 사모 전환사채` 등)
    method: str = ""  # 사모 / 공모
    coupon_rate: float | None = None  # 표면이자율(%)
    ytm_rate: float | None = None  # 만기이자율(%)
    maturity: str = ""  # 만기일
    conv_price: int | None = None  # 전환가액(원)
    conv_shares: int | None = None  # 전환 가능 주식수
    overhang_pct: float | None = None  # 발행주식총수 대비 비율(%) — **잠재 물량**
    conv_from: str = ""  # 전환청구 시작일
    conv_to: str = ""  # 전환청구 종료일
    outstanding: int | None = None  # 미상환 사채 잔액(원)
    refix_floor: int | None = None  # 전환가액 하향조정 하한(원)

    def to_json(self) -> dict[str, Any]:
        """jsonb에 넣을 형태 (`ksb_briefings.bodies`)."""
        return {
            "rcept_no": self.rcept_no,
            "event_type": self.event_type,
            "decided_on": self.decided_on,
            "amount": self.amount,
            "use_of_funds": [list(x) for x in self.use_of_funds],
            "kind": self.kind,
            "method": self.method,
            "coupon_rate": self.coupon_rate,
            "ytm_rate": self.ytm_rate,
            "maturity": self.maturity,
            "conv_price": self.conv_price,
            "conv_shares": self.conv_shares,
            "overhang_pct": self.overhang_pct,
            "conv_from": self.conv_from,
            "conv_to": self.conv_to,
            "outstanding": self.outstanding,
            "refix_floor": self.refix_floor,
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
    anomaly: Anomaly | None = None  # F4b 보조 신호 (v2.0). None = 생략됨
    insider: Insider | None = None  # F4b 보조 신호 (v2.0). None = 생략됨
    flow: Flow | None = None  # F12 시세 참고 (v2.0). None = 생략됨
    news: tuple[NewsItem, ...] = ()  # F11 뉴스. 빈 튜플 = 없음·생략
    bodies: tuple[EventBody, ...] = ()  # F15 공시 본문 (플래그된 공시만, v3.0)
    flows: InvestorFlows | None = None  # F17 기관·외국인 수급 30일 (v3.0). None = 생략됨
    # 아래 넷은 상위 evidence에서 그대로 온 표시용 값이다 (열이 아니다 — 렌더가 쓴다)
    conditions: tuple[tuple[str, bool, str], ...] = ()
    close: int = 0
    change_pct: float = 0.0
    in_progress: bool = False
    # 아래 셋은 열이 아니다 — 렌더 표기와 ksb_runs.detail 집계에 쓴다
    source: str = "mcp"  # 공시 출처: 'mcp' | 'rest'(폴백, D15)
    skipped: tuple[str, ...] = ()  # 생략된 보조 신호 이름 ('anomaly' · 'insider' · 'flow')
    error: str = ""  # level == 'error'일 때 원인

    @classmethod
    def from_signal(
        cls,
        signal: SignalRow,
        corp_code: str | None,
        level: Level,
        *,
        flags: tuple[Flag, ...] = (),
        disclosures: tuple[Disclosure, ...] = (),
        anomaly: Anomaly | None = None,
        insider: Insider | None = None,
        flow: Flow | None = None,
        news: tuple[NewsItem, ...] = (),
        bodies: tuple[EventBody, ...] = (),
        flows: InvestorFlows | None = None,
        summary: str | None = None,
        source: str = "mcp",
        skipped: tuple[str, ...] = (),
        error: str = "",
    ) -> Briefing:
        """신호 행에서 브리핑을 만든다 — 키·이름은 신호에서 그대로 온다."""
        return cls(
            d=signal.d,
            strategy=signal.strategy,
            ticker=signal.ticker,
            name=signal.name,
            conditions=signal.conditions,
            close=signal.close,
            change_pct=signal.change_pct,
            in_progress=signal.in_progress,
            corp_code=corp_code,
            level=level,
            flags=flags,
            disclosures=disclosures,
            anomaly=anomaly,
            insider=insider,
            flow=flow,
            news=news,
            bodies=bodies,
            flows=flows,
            summary=summary,
            source=source,
            skipped=skipped,
            error=error,
        )

    def link(self, rcept_no: str) -> str:
        """공시 원문 링크."""
        return dart_link(rcept_no)

    def signal_line(self) -> str:
        """종목 한 줄 — 상위 신호 메일과 같은 형태 (`가비아 [079940] 46,000원 +1.32%`)."""
        head = f"{self.name} [{self.ticker}]"
        if not self.close:
            return head
        mark = "(진행중)" if self.in_progress else ""
        return f"{head} {self.close:,}원 {self.change_pct:+.2f}%{mark}"

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
            "anomaly": self.anomaly.to_json() if self.anomaly else None,
            "insider": self.insider.to_json() if self.insider else None,
            "flow": self.flow.to_json() if self.flow else None,
            "news": [n.to_json() for n in self.news] if self.news else None,
            "bodies": [b.to_json() for b in self.bodies],
            "flows": None if self.flows is None else self.flows.to_json(),
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
