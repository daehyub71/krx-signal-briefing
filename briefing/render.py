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

**본문은 두 벌이다** — 같은 사실을 담되 형태가 다르다 (2026-08-29 시안 합의, `docs/DESIGN.md`):

| | 무엇 | 형태 |
|---|---|---|
| `text()` | 평문 대체본 | 링크를 따로 줄에 적는다. 스팸 점수와 HTML 미지원 클라이언트용 |
| `html()` | 사람이 읽는 본문 | 인덱스 표 → 위험 종목 카드 → 그 밖 압축 카드. **제목 자체가 링크** |

`html()`은 `text()`를 감싸지 않는다. `<pre>` 한 덩어리로는 조건·공시·뉴스가 같은 무게로 보여
위험 2건이 15종목 사이에 묻혔다 (2026-08-29 실측 — 그래서 다시 짰다).

표는 진짜 `<table>`이고 스타일은 전부 inline이다 — Gmail은 flex·grid·`<style>`을 믿을 수 없다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from briefing.models import Briefing, Disclosure, Level, NewsItem, dart_link

# 우리가 쓰는 문장에 들어가면 안 되는 말 (N1 v2, v3.0). 원문(공시·뉴스 제목)에는 적용하지 않는다.
#
# **v3.0에서 경계가 옮겨졌다** (D24): 근거 정합성은 되고 매매 판단은 안 된다.
# `호재`·`악재`는 금지어에서 뺐다 — 근거의 방향을 말하는 데 필요하고,
# 매매 판단은 아래 목록이 막는다. 대신 `진입`·`비중`을 넣었다.
#
# **RECIPIENTS 본인 한 사람 유지가 전제다** (R7 v2) — 남에게 보내면 판정문은 신고 대상이 된다.
FORBIDDEN: tuple[str, ...] = (
    "추천",
    "매수",
    "매도",
    "보류",
    "목표가",
    "손절",
    "여력",
    "이탈",
    "진입",
    "비중",
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

# 위험 유형이 없는 종목의 압축 카드 상한 (2026-08-29 합의).
# 15종목을 다 펴면 18,012자다 — 조건은 "5/5" 한 줄로 접고 공시·뉴스만 몇 건 보인다.
COMPACT_DISCLOSURES = 3
COMPACT_NEWS = 3

# ── 색 — 상위 알림 메일(`krx-signal-alerts/alerts/render.py`) 팔레트를 잇는다.
# 두 메일이 한 아침에 나란히 도착한다. 다른 팔레트를 쓰면 남의 메일처럼 보인다.
INK, SUB, MUTED, DIM = "#121829", "#3D465F", "#626D8A", "#8C96AE"
UP, DOWN = "#C9283E", "#1F63A8"  # 상승 붉게, 하락 푸르게 — 국내 관행
PAGE, BAND, LINE, HAIR = "#EEF1F7", "#F5F7FB", "#D8DEEB", "#F0F3F9"

# 등급별 테마: (점 색, 카드 배경, 테두리, 강조 글자)
THEMES: dict[str, tuple[str, str, str, str]] = {
    "red": ("#C9283E", "#FDF3F4", "#E7B8BF", "#8A1F2F"),
    "amber": ("#B76E00", "#FEF7EC", "#E8D2A8", "#7A4A00"),
    "none": ("#C6CDDE", "#FFFFFF", "#E1E6F0", SUB),
    "unknown": ("#C6CDDE", "#FFFFFF", "#E1E6F0", SUB),
    "error": ("#8C96AE", "#F5F7FB", "#D8DEEB", SUB),
}

FONT = "-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif"
NUM = "font-variant-numeric:tabular-nums"

# 규칙 id → 사람이 읽는 이름. 머리 밴드의 한 줄 판정에 쓴다.
# **사실만 적는다** — `전환사채 발행결정`은 되고 `오버행 주의`는 안 된다 (N1).
# `tests/test_render.py`가 flags.RULES의 모든 id에 라벨이 있는지 확인한다.
FLAG_LABELS: dict[str, str] = {
    "cb": "전환사채 발행결정",
    "bw": "신주인수권부사채 발행결정",
    "eb": "교환사채 발행결정",
    "rights_issue": "유상증자 결정",
    "controller_change": "최대주주 변경",
    "admin_issue": "관리종목 지정",
    "caution_issue": "투자주의환기종목 지정",
    "unfaithful": "불성실공시법인 지정",
    "delisting": "상장폐지 관련 공시",
    "embezzlement": "횡령·배임 혐의 발생",
    "rehabilitation": "회생절차 관련 공시",
    "audit": "감사의견 비적정",
    "trading_halt": "매매거래정지",
    "lawsuit": "소송 등의 제기",
    "treasury_sale": "자기주식 처분결정",
    "pledge": "최대주주 변경을 수반하는 주식담보 제공",
    "admin_warning": "관리종목 지정 우려",
    "unfaithful_warning": "불성실공시법인 지정 예고",
    "market_warning": "투자경고·위험종목 지정",
    "capital_reduction": "감자 결정",
    "insider_sell_cluster": "임원·주요주주 매도 군집",
}

SECTION_RISK = "위험 유형이 확인된 종목"
SECTION_REST = "확인된 위험 유형이 없는 종목"
NEWS_WHY = "공시가 설명하지 않는 움직임이라, 같은 기간 뉴스를 함께 싣습니다"

NL = chr(10)
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


def _news_lines(news: Sequence[NewsItem], cap: int = COMPACT_NEWS) -> list[str]:
    """📰 블록 (F11). 제목은 원문 그대로, 링크를 함께 단다.

    HTML과 같은 상한을 쓴다 — 평문은 링크를 따로 줄에 적어 훨씬 길어지는데,
    두 벌을 합친 메시지가 102,400 bytes를 넘으면 Gmail이 잘라낸다 (2026-08-29 실측).
    """
    if not news:
        return []
    out = [f"📰 뉴스 {len(news)}건 — 공시로 설명되지 않는 종목입니다"]
    for n in news[:cap]:
        day = _md(n.published) if n.published else "  ·  "
        out.append(f"     · {day} {n.title}")
        out.append(f"       {n.link}")
    if len(news) > cap:
        out.append(f"     · 외 {len(news) - cap}건")
    return out


def _headline(b: Briefing) -> str:
    """종목 한 줄 — 상위 메일과 같은 형태."""
    s = b.signal_line()
    return s


def _disclosure_lines(b: Briefing, cap: int = PLAIN_DISCLOSURES) -> list[str]:
    """공시 목록. **모든 항목에 원문 링크** (N2).

    플래그된 공시는 전부 싣고, 나머지는 최근 `cap`건까지만 싣는다.
    잘린 사실은 "외 N건"으로 드러낸다 — 조용히 자르면 "이게 다인가 보다"가 된다.
    """
    red_nos = {f.rcept_no for f in b.flags if f.level == "red"}
    flagged = {f.rcept_no for f in b.flags}
    out: list[str] = []
    plain_shown = omitted = 0
    for d in b.disclosures:
        if d.rcept_no not in flagged:
            if plain_shown >= cap:
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
    """종목 하나의 블록 — 조건 + 구분선 + 등급 + 공시 + 보조 + 뉴스 + 요약.

    **위험 유형이 확인된 종목에만 쓴다.** 나머지는 `_one_line()`으로 한 줄이다.
    """
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


def _one_line(b: Briefing) -> str:
    """위험 유형이 없는 종목 한 줄 — 평문 대체본용.

    평문은 링크를 따로 줄에 적어야 해서 HTML보다 훨씬 길어진다. 15종목을 다 펴면
    두 벌을 합친 메시지가 102,400 bytes를 넘어 **Gmail이 메일을 통째로 잘라낸다**
    (2026-08-29 실측: 첫 판 149,971 bytes). 그래서 평문은 위험 종목만 펴고 나머지는 한 줄로 적는다.
    상세와 원문 링크는 HTML 본문이 담는다.
    """
    bits = [b.signal_line()]
    if b.conditions:
        n_ok = sum(1 for _, ok, _ in b.conditions if ok)
        bits.append(f"조건 {n_ok}/{len(b.conditions)}")
    if b.level == "unknown":
        bits.append(UNKNOWN_WORDING)
    elif b.level == "error":
        bits.append(f"{ERROR_WORDING}: {b.error}" if b.error else ERROR_WORDING)
    else:
        bits.append(f"공시 {len(b.disclosures)}건")
        bits.append(NONE_WORDING.format(days=b.window_days))
    if b.news:
        bits.append(f"뉴스 {len(b.news)}건")
    if note := _skip_note(b):
        bits.append(note)
    line = "  " + " · ".join(bits)
    return f"{line}{NL}      💬 {b.summary}" if b.summary else line


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

    risky = [b for b in briefings if b.level in ("red", "amber")]
    rest = [b for b in briefings if b.level not in ("red", "amber")]

    lines = [f"[{day}] 신호 {len(briefings)}건에 최근 공시를 붙였습니다.", ""]
    lines.extend(_red_summary(briefings))
    if summary_error:
        lines.append(f"⚠ 요약 생성 실패 — 공시는 그대로 있습니다 ({summary_error})")
    lines.append("")
    for b in risky:
        lines.extend(_block(b))
        lines.append("")
    if rest:
        lines.append(f"■ {SECTION_REST} ({len(rest)}종목)")
        lines.extend(_one_line(b) for b in rest)
        lines.append("")
        lines.append("  공시·뉴스 원문 링크는 HTML 본문에 있습니다.")
        lines.append("")
    lines.append(LIMIT_NOTE)
    return "\n".join(lines) + "\n"


# ── HTML 본문 ────────────────────────────────────────────────────
#
# 규칙 셋:
#   ① 배치는 <table>만 — flex·grid는 안드로이드 Gmail에서 무너진다
#   ② **되풀이되는 치수는 클래스로, 뜻이 있는 색·굵기는 inline으로.**
#      Gmail은 <style>을 지원하지만 지우는 클라이언트도 있다. 지워져도 등급 색은 남아야 한다.
#      전부 inline으로 적었더니 메시지가 149,971 bytes가 되어 Gmail이 잘라냈다 (2026-08-29 실측).
#   ③ 사람이 쓴 값(종목명·제목)은 반드시 `escape()` — `A&B <홀딩스>`가 실재한다

# 클래스로 접은 치수. 지워져도 표는 표로 읽힌다.
STYLE = (
    "<style>"
    "table{border-collapse:collapse}"
    "td{font-variant-numeric:tabular-nums}"
    f".d{{padding:6px 10px 6px 0;color:{MUTED};white-space:nowrap;vertical-align:top;width:44px}}"
    ".b{padding:6px 0;vertical-align:top;line-height:1.5}"
    f".e{{border-bottom:1px solid {HAIR}}}"
    f".x{{padding:8px 6px;border-bottom:1px solid {PAGE}}}"
    ".r{text-align:right}"
    f".s{{font-size:11px;letter-spacing:.1em;color:{DIM};font-weight:700;margin-bottom:8px}}"
    ".c{padding:14px 28px 0}"
    ".p{padding:11px 16px 3px}"
    ".t{width:100%;font-size:13px}"
    f".k{{padding:4px 0;color:{SUB};width:56%}}"
    f".v{{padding:4px 0;color:{INK};text-align:right}}"
    f".m{{font-size:12px;color:{MUTED};line-height:1.7}}"
    "</style>"
)

# 메시지 전체가 이 크기를 넘으면 Gmail이 "[메시지 전체 보기]"로 잘라낸다.
# 평문+HTML이 base64로 부풀므로 원본 HTML은 훨씬 작아야 한다.
GMAIL_CLIP_BYTES = 102_400
HTML_BUDGET = 60_000


def _eok(won: int) -> str:
    """원 → `1,457억`. 반올림하지 않고 버린다 — 있는 것보다 크게 보이면 안 된다."""
    return f"{won // 100_000_000:,}억"


def _pct(v: float) -> str:
    """등락률 — 상승 붉게, 하락 푸르게 (국내 관행, 상위 메일과 같다)."""
    return f'<span style="color:{UP if v >= 0 else DOWN}">{v:+.2f}%</span>'


def _dot(level: str, size: int = 7) -> str:
    """등급 점. **이모지를 쓰지 않는다** — 클라이언트마다 다른 그림이 온다."""
    color = THEMES.get(level, THEMES["none"])[0]
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'background:{color}"></span>'
    )


def _split_disclosures(b: Briefing, cap: int) -> tuple[list[Disclosure], list[Disclosure], int]:
    """공시를 (위험 유형에 걸린 것, 보일 나머지, 생략된 수)로 나눈다.

    **플래그된 공시는 먼저 오고 절대 잘리지 않는다** — 그것 때문에 보내는 메일이다.
    나머지는 `cap`건까지만 보이고, 잘린 수는 "외 N건"으로 드러낸다.
    """
    flagged_nos = {f.rcept_no for f in b.flags}
    flagged = [d for d in b.disclosures if d.rcept_no in flagged_nos]
    plain = [d for d in b.disclosures if d.rcept_no not in flagged_nos]
    return flagged, plain[:cap], max(0, len(plain) - cap)


def _level_of(b: Briefing, rcept_no: str) -> str:
    """이 공시가 걸린 규칙의 등급. 안 걸렸으면 빈 문자열."""
    for f in b.flags:
        if f.rcept_no == rcept_no:
            return f.level
    return ""


def _row(date_cell: str, body: str, *, last: bool = False) -> str:
    """날짜 | 내용 두 칸 짜리 표 한 줄. 목록은 전부 이 모양이다."""
    e = "" if last else " e"
    return f'<tr><td class="d{e}">{date_cell}</td><td class="b{e}">{body}</td></tr>'


def _chip(text: str, bg: str, fg: str = "#FFFFFF", border: str = "") -> str:
    """작은 표시 칩 (`위험`·`정정`)."""
    edge = f"border:1px solid {border};" if border else ""
    return (
        f'<span style="display:inline-block;{edge}background:{bg};color:{fg};font-size:10px;'
        f'font-weight:700;padding:2px 5px">{text}</span>'
    )


def _disclosure_row(b: Briefing, d: Disclosure, *, last: bool = False, tail: str = "") -> str:
    """공시 한 줄 — **제목 자체가 원문 링크다** (N2).

    예전에는 URL을 제목 아래 별도 줄에 적어 줄 수가 두 배였다 (2026-08-29 시안에서 걷어냄).
    """
    lv = _level_of(b, d.rcept_no)
    weight = "font-weight:700;" if lv else ""
    title = (
        f'<a href="{dart_link(d.rcept_no)}" style="{weight}color:{INK if lv else SUB}">'
        f"{escape(d.report_nm)}</a>"
    )
    mark = _chip("정정", "#FFFFFF", MUTED, border="#C6CDDE") + " " if d.corrected else ""
    if lv:
        tail = " " + _chip("위험" if lv == "red" else "주의", THEMES[lv][0]) + tail
    if d.flr_nm and d.flr_nm != b.name:
        tail += f' <span style="color:{DIM};font-size:11px">{escape(d.flr_nm)}</span>'
    return _row(_md(d.rcept_dt), f"{mark}{title}{tail}", last=last)


def _news_row(n: NewsItem, *, last: bool = False, tail: str = "") -> str:
    """뉴스 한 줄 — 제목이 링크. 제목은 **원문**이라 금지어 검사를 받지 않는다."""
    day = _md(n.published) if n.published else ""
    body = f'<a href="{escape(n.link)}" style="color:{SUB}">{escape(n.title)}</a>{tail}'
    return _row(day, body, last=last)


def _label(text: str, extra: str = "") -> str:
    """카드 안의 작은 구역 이름."""
    more = f' <span style="color:#C6CDDE;font-weight:400">{extra}</span>' if extra else ""
    return f'<div class="s">{text}{more}</div>'


def _more(n: int) -> str:
    """"외 N건" — 잘린 사실을 조용히 숨기지 않는다."""
    return f' <span style="color:{DIM}">· 외 {n}건</span>' if n else ""


def _list(label: str, rows: list[str], extra: str = "") -> str:
    """제목 붙은 목록 한 덩어리."""
    return (
        f'<tr><td class="p">{_label(label, extra)}'
        f'<table width="100%" class="t">{"".join(rows)}</table></td></tr>'
    )


def _meta_bar(b: Briefing) -> str:
    """카드 바닥의 참고값 줄 — 시총 · 거래대금 · 이상 점수 · 생략 표기."""
    bits: list[str] = []
    if b.flow is not None:
        f = b.flow
        md = f"{f.bas_dd[4:6]}/{f.bas_dd[6:8]}"
        bits.append(f'시총 <b style="color:{SUB}">{_eok(f.mktcap)}</b>')
        bits.append(f'{f.days}일 거래대금 <b style="color:{SUB}">{_eok(f.trdval_5d)}</b>')
        bits.append(f'<span style="color:{DIM}">{md} 기준</span>')
    if b.anomaly is not None:
        bits.append(
            f'공시 이상 점수 <b style="color:{SUB}">{b.anomaly.score}/100</b>'
            f" {escape(b.anomaly.verdict)}"
        )
    if b.insider is not None and b.insider.sell_cluster:
        i = b.insider
        bits.append(
            f'임원·주요주주 매도 <b style="color:{SUB}">{i.sell_events}건</b>'
            f" · {i.unique_sellers}명 · 순변동 {i.net_change_shares:+,}주"
        )
    note = _skip_note(b)
    if not bits and not note:
        return ""
    warn = f'<div style="padding-top:6px;color:{DIM}">{escape(note)}</div>' if note else ""
    return (
        f'<tr><td style="padding:12px 16px 13px">'
        f'<div class="m" style="border-top:1px solid {HAIR};padding-top:10px">'
        f'{"　".join(bits)}{warn}</div></td></tr>'
    )


def _summary_line(b: Briefing) -> str:
    """Claude 한 줄 요약 (F14). 없으면 아무것도 그리지 않는다."""
    if not b.summary:
        return ""
    return (
        f'<tr><td style="padding:11px 16px 0"><div style="background:{BAND};'
        f'padding:10px 13px;font-size:13px;color:{SUB};line-height:1.6">'
        f"{escape(b.summary)}</div></td></tr>"
    )


def _verdict_text(b: Briefing) -> str:
    """머리 밴드의 한 줄 판정 — 사실만 (N1)."""
    if b.level == "unknown":
        return UNKNOWN_WORDING
    if b.level == "error":
        return f"{ERROR_WORDING}: {escape(b.error)}" if b.error else ERROR_WORDING
    n = len(b.disclosures)
    if b.level == "none":
        n_ok = sum(1 for _, ok, _ in b.conditions if ok)
        cond = f"신호 조건 {n_ok}/{len(b.conditions)}　" if b.conditions else ""
        return f"{cond}공시 {n}건　<b>{NONE_WORDING.format(days=b.window_days)}</b>"
    kinds = sorted({f.rule for f in b.flags})
    corrected_nos = {d.rcept_no for d in b.disclosures if d.corrected}
    corrected = sum(1 for f in b.flags if f.rcept_no in corrected_nos)
    fix = f" (정정 {corrected}건 포함)" if corrected else ""
    label = FLAG_LABELS.get(kinds[0], kinds[0]) if len(kinds) == 1 else "위험 유형"
    return f"{escape(label)} {len(b.flags)}건{fix} — 최근 {b.window_days}일 공시 {n}건 중"


def _head_band(b: Briefing, *, compact: bool) -> str:
    """카드 머리 — 종목명 · 종가 · 등락 · 한 줄 판정."""
    _d, bg, line, ink = THEMES.get(b.level, THEMES["none"])
    size = 15 if compact else 16
    price = ""
    if b.close:
        mark = f' <span style="color:{DIM};font-size:12px">진행중</span>' if b.in_progress else ""
        price = (
            f'{b.close:,}<span style="font-size:12px;font-weight:400;color:{SUB}">원</span> '
            f"{_pct(b.change_pct)}{mark}"
        )
    pad = "12px 16px 10px" if compact else "14px 16px 12px"
    weight = "700" if b.level in ("red", "amber") else "400"
    return (
        f'<tr><td style="padding:{pad};background:{bg};border-bottom:1px solid {line}">'
        f'<table width="100%"><tr>'
        f'<td style="font-size:{size}px;font-weight:800;letter-spacing:-.02em">'
        f'{escape(b.name)} <span style="color:{DIM};font-weight:400;font-size:12px">'
        f"{escape(b.ticker)}</span></td>"
        f'<td class="r" style="font-size:{size - 1}px;font-weight:700">{price}</td></tr></table>'
        f'<div style="margin-top:8px;font-size:{12 if compact else 13}px;color:{ink};'
        f'font-weight:{weight};line-height:1.55">{_verdict_text(b)}</div></td></tr>'
    )


def _conditions_table(b: Briefing) -> str:
    """신호 조건 표 — 상위 메일이 보낸 근거값을 그대로 편다."""
    if not b.conditions:
        return ""
    rows = [
        f'<tr{f" style=background:{BAND}" if i % 2 else ""}>'
        f'<td class="k">{"" if ok else f"<span style=color:{DIM}>미충족 </span>"}'
        f'{escape(label)}</td><td class="v">{escape(actual)}</td></tr>'
        for i, (label, ok, actual) in enumerate(b.conditions)
    ]
    n_ok = sum(1 for _, ok, _ in b.conditions if ok)
    head = _label(f'신호 조건 <span style="color:{UP}">{n_ok}/{len(b.conditions)}</span>')
    return (
        f'<tr><td style="padding:10px 16px 4px">{head}'
        f'<table width="100%" style="width:100%;font-size:12px">{"".join(rows)}</table>'
        f"</td></tr>"
    )


def _card(b: Briefing) -> str:
    """위험 유형이 확인된 종목의 전체 카드 — 공시 전부 + 조건 전부 + 참고값."""
    dot, _bg, line, _ink = THEMES.get(b.level, THEMES["none"])
    flagged, plain, omitted = _split_disclosures(b, PLAIN_DISCLOSURES)
    shown = flagged + plain
    rows = [
        _disclosure_row(
            b,
            d,
            last=(i == len(shown) - 1),
            tail=_more(omitted) if i == len(shown) - 1 else "",
        )
        for i, d in enumerate(shown)
    ]
    extra = "— 위험 유형을 먼저 싣습니다" if flagged and plain else ""
    body = _list(f"공시 {len(b.disclosures)}건", rows, extra) if shown else ""
    return (
        f'<tr><td class="c"><table width="100%" '
        f'style="width:100%;border:1px solid {line};border-left:4px solid {dot}">'
        f"{_head_band(b, compact=False)}{_summary_line(b)}{body}"
        f"{_conditions_table(b)}{_meta_bar(b)}</table></td></tr>"
    )


def _card_compact(b: Briefing) -> str:
    """위험 유형이 없는 종목의 압축 카드 — 조건은 한 줄로 접고 공시·뉴스만 몇 건."""
    _d, _bg, line, _ink = THEMES.get(b.level, THEMES["none"])
    parts = [_head_band(b, compact=True), _summary_line(b)]

    _flagged, plain, omitted = _split_disclosures(b, COMPACT_DISCLOSURES)
    if plain:
        parts.append(
            _list(
                "최근 공시",
                [
                    _disclosure_row(
                        b, d, last=(i == len(plain) - 1),
                        tail=_more(omitted) if i == len(plain) - 1 else "",
                    )
                    for i, d in enumerate(plain)
                ],
            )
        )
    if b.news:
        shown = b.news[:COMPACT_NEWS]
        rest = len(b.news) - len(shown)
        parts.append(
            _list(
                "같은 기간 뉴스",
                [
                    _news_row(
                        n, last=(i == len(shown) - 1),
                        tail=_more(rest) if i == len(shown) - 1 else "",
                    )
                    for i, n in enumerate(shown)
                ],
            )
        )
    parts.append(_meta_bar(b))
    return (
        f'<tr><td class="c"><table width="100%" style="width:100%;border:1px solid {line}">'
        f'{"".join(parts)}</table></td></tr>'
    )


def _index_table(briefings: Sequence[Briefing]) -> str:
    """맨 위 인덱스 표 — **15종목을 한 번에 훑는 유일한 자리다**.

    이것이 없으면 위험 2건을 찾으려 본문을 끝까지 읽어야 한다 (2026-08-29 시안 근거).
    아래 압축 카드가 예산 때문에 잘려도 **모든 종목은 이 표에 남는다.**
    """
    if not briefings:
        return ""
    th = (
        f"padding:7px 6px;font-size:11px;color:{MUTED};font-weight:700;"
        f"border-bottom:1px solid {LINE}"
    )
    head = f'<td style="{th};width:16px"></td><td style="{th}">종목</td>'
    for name in ("종가", "등락", "공시", "시총"):
        head += f'<td class="r" style="{th}">{name}</td>'
    rows = [f'<tr style="background:{BAND}">{head}</tr>']
    for b in briefings:
        risky = b.level in ("red", "amber")
        bg = f" style=background:{THEMES[b.level][1]}" if risky else ""
        w = ' style="font-weight:700"' if risky else ""
        if b.level in ("unknown", "error"):
            count = f'<span style="color:{DIM}">—</span>'
        elif b.flags:
            count = (
                f'<b style="color:{THEMES[b.level][0]}">{len(b.flags)}</b>'
                f'<span style="color:{DIM}">/{len(b.disclosures)}</span>'
            )
        else:
            count = f'<span style="color:{DIM}">0/{len(b.disclosures)}</span>'
        cap = _eok(b.flow.mktcap) if b.flow is not None else "—"
        rows.append(
            f"<tr{bg}>"
            f'<td class="x">{_dot(b.level)}</td>'
            f'<td class="x"{w}>{escape(b.name)} '
            f'<span style="color:{DIM};font-weight:400;font-size:11px">'
            f"{escape(b.ticker)}</span></td>"
            f'<td class="x r">{f"{b.close:,}" if b.close else "—"}</td>'
            f'<td class="x r"{w}>{_pct(b.change_pct) if b.close else "—"}</td>'
            f'<td class="x r">{count}</td>'
            f'<td class="x r" style="color:{SUB}">{cap}</td></tr>'
        )
    return (
        f'<tr><td style="padding:22px 28px 4px">'
        f'<div style="font-size:11px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"한눈에 보기</div></td></tr>"
        f'<tr><td style="padding:8px 28px 24px">'
        f'<table width="100%" class="t">{"".join(rows)}</table></td></tr>'
    )


def _section(title: str, n: int, level: str, note: str = "") -> str:
    """구역 머리 — `위험 유형이 확인된 종목 2`."""
    sub = f'<div style="margin-top:6px;font-size:12px;color:{DIM}">{note}</div>' if note else ""
    return (
        f'<tr><td style="padding:26px 28px 0">'
        f'<div style="border-top:1px solid {LINE};padding-top:20px">'
        f'{_dot(level, 9)}<span style="margin-left:8px;font-size:14px;font-weight:800">'
        f'{title}</span> <span style="color:{DIM};font-size:13px">{n}</span>{sub}</div>'
        f"</td></tr>"
    )


def _shell(inner: str) -> str:
    """메일 바깥 껍데기 — 600px 고정, 회색 바탕에 흰 판."""
    return (
        f'{STYLE}<table width="100%" style="width:100%;background:{PAGE};'
        f'font-family:{FONT};color:{INK}">'
        f'<tr><td style="padding:20px 10px">'
        f'<table width="600" align="center" style="width:600px;max-width:600px;'
        f'background:#FFFFFF;border:1px solid {LINE}">{inner}</table></td></tr></table>'
    )


def _header(briefings: Sequence[Briefing], data_date: date, summary_error: str) -> str:
    """머리 — 날짜 · 한 문장 · 등급 칩."""
    c = _counts(briefings)
    chips: list[tuple[str, str, str]] = []
    if c.get("red"):
        chips.append((f"위험 유형 확인 {c['red']}", THEMES["red"][0], "#FFFFFF"))
    if c.get("amber"):
        chips.append((f"주의 {c['amber']}", THEMES["amber"][0], "#FFFFFF"))
    if c.get("none"):
        chips.append((f"확인된 유형 없음 {c['none']}", PAGE, SUB))
    if c.get("unknown"):
        chips.append((f"코드 미확인 {c['unknown']}", PAGE, SUB))
    if c.get("error"):
        chips.append((f"조회 실패 {c['error']}", BAND, MUTED))
    cells = ""
    for i, (t, bg, fg) in enumerate(chips):
        if i:
            cells += '<td style="width:6px"></td>'
        cells += (
            f'<td style="background:{bg};color:{fg};font-size:12px;font-weight:700;'
            f'padding:5px 11px">{escape(t)}</td>'
        )
    warn = (
        f'<div class="m" style="margin-top:12px">⚠ 요약 생성 실패 — 공시는 그대로 있습니다'
        f" ({escape(summary_error)})</div>"
        if summary_error
        else ""
    )
    days = briefings[0].window_days if briefings else 30
    return (
        f'<tr><td style="padding:26px 28px 20px;border-bottom:3px solid {INK}">'
        f'<div style="font-size:12px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"공시 브리핑 · {data_date.year}. {data_date.month:02d}. {data_date.day:02d}</div>"
        f'<div style="font-size:23px;font-weight:800;letter-spacing:-.02em;margin-top:8px;'
        f'line-height:1.3">신호 {len(briefings)}건에 최근 {days}일 공시를 붙였습니다</div>'
        f'<table style="margin-top:14px"><tr>{cells}</tr></table>{warn}</td></tr>'
    )


def _footer() -> str:
    """꼬리 — 한계 문구 (R7·N1). **여기는 절대 지우지 않는다.**"""
    return (
        f'<tr><td style="padding:26px 28px">'
        f'<div class="m" style="border-top:3px solid {INK};padding-top:14px">{LIMIT_NOTE}<br>'
        f"공시 원문은 금융감독원 전자공시시스템(DART)에서 확인할 수 있습니다.</div></td></tr>"
    )


def _empty(day: str, message: str) -> str:
    """대상이 없을 때의 짧은 본문."""
    return _shell(
        f'<tr><td style="padding:30px 28px;border-bottom:3px solid {INK}">'
        f'<div style="font-size:12px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"공시 브리핑 · {day}</div>"
        f'<div style="font-size:20px;font-weight:800;margin-top:8px">{escape(message)}</div>'
        f'</td></tr><tr><td style="padding:22px 28px 26px">'
        f'<div class="m">{LIMIT_NOTE}</div></td></tr>'
    )


def _build(
    briefings: Sequence[Briefing], data_date: date, summary_error: str, cards: int
) -> str:
    """본문 한 벌. `cards`는 압축 카드를 몇 종목까지 펼칠지 — 예산 맞추기용."""
    risky = [b for b in briefings if b.level in ("red", "amber")]
    rest = [b for b in briefings if b.level not in ("red", "amber")]
    parts = [_header(briefings, data_date, summary_error), _index_table(briefings)]
    if risky:
        parts.append(_section(SECTION_RISK, len(risky), risky[0].level))
        parts.extend(_card(b) for b in risky)
    if rest:
        shown = rest[:cards]
        note = NEWS_WHY if any(b.news for b in shown) else ""
        parts.append(_section(SECTION_REST, len(rest), "none", note))
        parts.extend(_card_compact(b) for b in shown)
        if len(rest) > len(shown):
            parts.append(
                f'<tr><td class="c"><div class="m" style="border:1px dashed {LINE};'
                f'padding:13px 16px;text-align:center">나머지 {len(rest) - len(shown)}종목은 '
                f"위 「한눈에 보기」 표에 있습니다 — 메일 길이를 넘지 않으려 카드를 접었습니다"
                f"</div></td></tr>"
            )
    parts.append(_footer())
    return _shell("".join(parts))


def html(
    briefings: Sequence[Briefing],
    data_date: date,
    *,
    stale: bool = False,
    summary_error: str = "",
) -> str:
    """HTML 본문 (F7) — 인덱스 표 → 위험 종목 카드 → 그 밖 압축 카드.

    `text()`를 감싸지 않는다. 두 벌을 따로 만든다 (모듈 docstring의 표 참조).

    **예산을 넘으면 압축 카드부터 접는다** — Gmail이 잘라내면 꼬리의 한계 문구까지 사라진다.
    위험 종목 카드와 인덱스 표는 절대 접지 않는다: 접을 것과 접지 않을 것의 우선순위가 곧 설계다.
    """
    day = _md(data_date)
    if stale:
        return _empty(day, "신호 배치가 데이터 지연으로 신호를 만들지 않았습니다")
    if not briefings:
        return _empty(day, "오늘 신호가 없습니다")

    rest_n = sum(1 for b in briefings if b.level not in ("red", "amber"))
    for cards in range(rest_n, -1, -1):
        doc = _build(briefings, data_date, summary_error, cards)
        if len(doc) <= HTML_BUDGET or cards == 0:
            return doc + "\n"
    return _build(briefings, data_date, summary_error, 0) + "\n"
