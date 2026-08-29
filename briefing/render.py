"""메일 제목·본문 생성 — 순수 함수 (SPEC F7·F8·N1·N2).

네트워크도 DB도 모른다. 브리핑 목록을 받아 문자열을 돌려줄 뿐이다.

**문구 경계가 이 모듈의 가장 큰 책임이다** (N1). 사실 나열은 되고 판단은 안 된다:

| 써도 되는 말 | 쓰면 안 되는 말 |
|---|---|
| `최근 30일 공시 중 확인된 위험 유형 없음` | `리스크: 없음` |
| `08/22 전환사채권발행결정` + 링크 | `오버행 주의 — 진입 보류` |

공시 제목·뉴스 제목은 **원문**이라 금지어가 들어 있어도 그대로 싣는다 —
우리가 쓴 문장만 규칙을 지킨다.
`tests/test_render.py`가 원문을 지운 나머지에서 금지어를 찾는다.

모든 공시 항목에 DART 원문 링크를 단다 (N2). 생략된 층은 조용히 빠지지 않고 `⚠`로 드러낸다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from briefing.models import Briefing, Level, NewsItem, dart_link

# 우리가 쓰는 문장에 들어가면 안 되는 말 (N1). 원문(공시·뉴스 제목)에는 적용하지 않는다.
FORBIDDEN: tuple[str, ...] = (
    "추천",
    "매수",
    "매도",
    "보류",
    "호재",
    "악재",
    "목표가",
    "손절",
    "여력",
    "이탈",
)

LEVEL_MARK: dict[Level, str] = {
    "red": "🔴",
    "amber": "🟡",
    "none": "📄",
    "unknown": "❔",
    "error": "⚠",
}

NONE_WORDING = "최근 {days}일 공시 중 확인된 위험 유형 없음"
UNKNOWN_WORDING = "DART 코드 미확인 — 공시를 보지 못했습니다"
ERROR_WORDING = "공시 조회 실패"

SKIP_WORDING: dict[str, str] = {
    "anomaly": "보조 신호 생략",
    "insider": "보조 신호 생략",
    "flow": "시세 참고 생략",
    "news": "뉴스 생략",
}

# 플래그되지 않은 공시를 몇 건까지 보일지. 넘으면 "외 N건"으로 줄인다 —
# 15종목 × 16건이면 2만 자가 넘어 읽을 수 없다 (2026-08-29 실측).
# **플래그된 공시는 이 제한을 받지 않는다** — 그것 때문에 보내는 메일이다.
PLAIN_DISCLOSURES = 4

RULE = "─" * 45
LIMIT_NOTE = "이 메일은 공시 사실을 나열합니다. 매매 판단의 근거가 아닙니다."


def _md(d: date) -> str:
    """`08/25` 형태."""
    return f"{d.month:02d}/{d.day:02d}"


def _counts(briefings: Sequence[Briefing]) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in briefings:
        out[b.level] = out.get(b.level, 0) + 1
    return out


def subject(briefings: Sequence[Briefing], data_date: date, *, stale: bool = False) -> str:
    """메일 제목 (F8) — **제목만 보고 오늘 열어 볼지** 판단할 수 있어야 한다."""
    day = _md(data_date)
    if stale:
        return f"[브리핑 없음] {day} — 신호 배치 데이터 지연"
    if not briefings:
        return f"[브리핑 없음] {day}"
    c = _counts(briefings)
    parts = [f"🔴 {c['red']}"] if c.get("red") else []
    if c.get("amber"):
        parts.append(f"🟡 {c['amber']}")
    if c.get("none"):
        parts.append(f"확인된 위험 유형 없음 {c['none']}")
    if c.get("unknown"):
        parts.append(f"코드 미확인 {c['unknown']}")
    head = f"[브리핑] {day} — " + " · ".join(parts or ["대상 없음"])
    return f"⚠ 공시 조회 실패 {c['error']}건 · {head}" if c.get("error") else head


def _skip_note(b: Briefing) -> str:
    """생략된 층을 한 줄로. 중복 없이 순서를 지킨다."""
    seen: list[str] = []
    for name in b.skipped:
        word = SKIP_WORDING.get(name, name)
        if word not in seen:
            seen.append(word)
    return f"⚠ {' · '.join(seen)}" if seen else ""


def _side_lines(b: Briefing) -> list[str]:
    """보조 신호·시세 참고 — 등급을 바꾸지 않는 참고값 (F4b·F12)."""
    lines: list[str] = []
    if b.anomaly is not None:
        lines.append(f"📊 공시 이상 점수 {b.anomaly.score}/100 · {b.anomaly.verdict}")
    if b.insider is not None and b.insider.sell_cluster:
        i = b.insider
        lines.append(
            f"👤 임원·주요주주 매도 군집 — {i.sell_events}건 · {i.unique_sellers}명"
            f" · 순변동 {i.net_change_shares:+,}주"
        )
    if b.flow is not None:
        lines.append(f"💰 {b.flow.display()}")
    return lines


def _news_lines(news: Sequence[NewsItem]) -> list[str]:
    """📰 블록 (F11). 제목은 원문 그대로, 링크를 함께 단다."""
    if not news:
        return []
    out = [f"📰 뉴스 {len(news)}건 — 공시로 설명되지 않는 종목입니다"]
    for n in news:
        day = _md(n.published) if n.published else "  ·  "
        out.append(f"     · {day} {n.title}")
        out.append(f"       {n.link}")
    return out


def _headline(b: Briefing) -> str:
    """종목 한 줄 — 상위 메일과 같은 형태."""
    s = b.signal_line()
    return s


def _disclosure_lines(b: Briefing) -> list[str]:
    """공시 목록. **모든 항목에 원문 링크** (N2).

    플래그된 공시는 전부 싣고, 나머지는 최근 `PLAIN_DISCLOSURES`건까지만 싣는다.
    잘린 사실은 "외 N건"으로 드러낸다 — 조용히 자르면 "이게 다인가 보다"가 된다.
    """
    red_nos = {f.rcept_no for f in b.flags if f.level == "red"}
    flagged = {f.rcept_no for f in b.flags}
    out: list[str] = []
    plain_shown = omitted = 0
    for d in b.disclosures:
        if d.rcept_no not in flagged:
            if plain_shown >= PLAIN_DISCLOSURES:
                omitted += 1
                continue
            plain_shown += 1
        mark = ""
        if d.rcept_no in flagged:
            mark = " ←🔴" if d.rcept_no in red_nos else " ←🟡"
        fix = "[정정] " if d.corrected else ""
        out.append(f"     · {_md(d.rcept_dt)} {fix}{d.report_nm}{mark}")
        out.append(f"       {dart_link(d.rcept_no)}")
    if omitted:
        out.append(f"     · 외 {omitted}건 (위험 유형에 걸리지 않은 공시)")
    return out


def _status_line(b: Briefing) -> str:
    """등급 줄 — 공시 건수와 판정 요약."""
    mark = LEVEL_MARK.get(b.level, "·")
    if b.level == "unknown":
        return f"  {mark} {UNKNOWN_WORDING}"
    if b.level == "error":
        return f"  {mark} {ERROR_WORDING}: {b.error}" if b.error else f"  {mark} {ERROR_WORDING}"
    n = len(b.disclosures)
    if b.level == "none":
        return f"  {mark} 공시 {n}건 · " + NONE_WORDING.format(days=b.window_days)
    return f"  {mark} 공시 {n}건 · 위험 유형 {len(b.flags)}건"


def _block(b: Briefing) -> list[str]:
    """종목 하나의 블록 — 조건 5줄 + 구분선 + 등급 + 공시 + 보조 + 뉴스 + 요약."""
    lines = [_headline(b)]
    for label, ok, actual in b.conditions:
        lines.append(f"  {'✓' if ok else '✗'} {label} : {actual}")
    lines.append(f"  {RULE}")
    lines.append(_status_line(b))
    lines.extend(_disclosure_lines(b))
    lines.extend(f"  {x}" for x in _side_lines(b))
    lines.extend(f"  {x}" for x in _news_lines(b.news))
    if b.summary:
        lines.append(f"  💬 {b.summary}")
    if note := _skip_note(b):
        lines.append(f"  {note}")
    return lines


def _red_summary(briefings: Sequence[Briefing]) -> list[str]:
    """상단 요약 — 🔴가 있으면 본문을 다 읽기 전에 보인다."""
    reds = [b for b in briefings if b.level == "red"]
    ambers = [b for b in briefings if b.level == "amber"]
    out: list[str] = []
    if reds:
        out.append(f"🔴 {len(reds)}건: " + ", ".join(b.name for b in reds))
    if ambers:
        out.append(f"🟡 {len(ambers)}건: " + ", ".join(b.name for b in ambers))
    return out


def text(
    briefings: Sequence[Briefing],
    data_date: date,
    *,
    stale: bool = False,
    summary_error: str = "",
) -> str:
    """평문 본문 (F7). HTML 태그를 쓰지 않는다 — 스팸 점수와 대체본을 위해."""
    day = _md(data_date)
    if stale:
        return (
            f"[{day}] 브리핑 대상 없음 — 신호 배치가 데이터 지연으로 신호를 만들지 않았습니다.\n\n"
            f"{LIMIT_NOTE}\n"
        )
    if not briefings:
        return f"[{day}] 브리핑 대상 없음 — 오늘 신호가 없습니다.\n\n{LIMIT_NOTE}\n"

    lines = [f"[{day}] 신호 {len(briefings)}건에 최근 공시를 붙였습니다.", ""]
    lines.extend(_red_summary(briefings))
    if summary_error:
        lines.append(f"⚠ 요약 생성 실패 — 공시는 그대로 있습니다 ({summary_error})")
    lines.append("")
    for b in briefings:
        lines.extend(_block(b))
        lines.append("")
    lines.append(LIMIT_NOTE)
    return "\n".join(lines) + "\n"


def html(
    briefings: Sequence[Briefing],
    data_date: date,
    *,
    stale: bool = False,
    summary_error: str = "",
) -> str:
    """HTML 본문. 종목명·공시·뉴스 제목을 **반드시 이스케이프**한다 — `&`가 든 이름이 실재한다."""
    body = text(briefings, data_date, stale=stale, summary_error=summary_error)
    style = "font-family:ui-monospace,Menlo,monospace;font-size:13px;white-space:pre-wrap"
    out: list[str] = [f'<pre style="{style}">']
    for line in body.splitlines():
        marked = escape(line)
        for b in briefings:
            for d in b.disclosures:
                url = dart_link(d.rcept_no)
                if line.strip() == url:
                    marked = f'<a href="{url}">{escape(url)}</a>'
            for n in b.news:
                if line.strip() == n.link:
                    marked = f'<a href="{escape(n.link)}">{escape(n.link)}</a>'
        out.append(marked)
    out.append("</pre>")
    return "\n".join(out) + "\n"
