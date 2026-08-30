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

from briefing import routine
from briefing.models import Briefing, Disclosure, Level, NewsItem, dart_link
from briefing.verdict import NEUTRAL, Verdict

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

# 금지어 검사에서 빼는 **합성어** (v3.0). `순매도`는 수급을 말하는 유일한 말인데
# `매도`에 걸려 분석문이 통째로 버려진다 — 2026-08-30 실호출에서 실제로 겪었다.
# 매매 판단(`매도 판단`·`매수 시점`)은 그대로 막힌다: 여기 적힌 형태만 예외다.
ALLOWED_COMPOUNDS: tuple[str, ...] = ("순매수", "순매도", "매수세", "매도세", "매수관여율")


def has_forbidden(text: str) -> str:
    """우리 문장에 금지어가 있으면 그 말을, 없으면 빈 문자열 (N1 v2).

    `순매수`·`순매도` 같은 사실 표현은 먼저 지우고 검사한다.
    """
    rest = text
    for word in ALLOWED_COMPOUNDS:
        rest = rest.replace(word, " ")
    return next((w for w in FORBIDDEN if w in rest), "")


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
    "investor_flows": "수급 생략",
    "news": "뉴스 생략",
}

# 플래그되지 않은 공시를 몇 건까지 보일지. 넘으면 "외 N건"으로 줄인다 —
# 15종목 × 16건이면 2만 자가 넘어 읽을 수 없다 (2026-08-29 실측).
# **플래그된 공시는 이 제한을 받지 않는다** — 그것 때문에 보내는 메일이다.
EXCERPT_LEN = 150  # 발췌 길이 (DESIGN G10). 전문은 페이지로 보낸다
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


def _plain_excerpt(text: str | None) -> str:
    """평문에 실을 발췌.

    분석 전문(종목당 최대 2,000자)을 평문에도 실으면 두 벌을 합친 메시지가
    Gmail 클리핑 한계를 넘는다 — 실측 115,704 bytes (2026-08-30).
    전문은 페이지가 담는다 (F20).
    """
    body = (text or "").strip()
    if len(body) <= EXCERPT_LEN:
        return body
    cut = body[:EXCERPT_LEN]
    stop = max(cut.rfind("다."), cut.rfind("."))
    return (cut[: stop + 1] if stop > EXCERPT_LEN // 2 else cut) + " …"


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
    if b.news:
        # 뉴스 목록은 HTML과 전문 페이지가 담는다 — 평문에 URL까지 넣으면 메시지가 커진다.
        lines.append(f"  📰 뉴스 {len(b.news)}건 — HTML 본문과 전문 페이지에 있습니다")
    if b.summary:
        lines.append(f"  💬 {_plain_excerpt(b.summary)}")
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
    return f"{line}{NL}      💬 {_plain_excerpt(b.summary)}" if b.summary else line


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


# ── HTML 본문 (v3.0 — DESIGN §8) ─────────────────────────────────
#
# 규칙 넷:
#   ① 배치는 <table>만 — flex·grid는 안드로이드 Gmail에서 무너진다
#   ② 되풀이되는 치수는 <style> 클래스로, 뜻이 있는 색·굵기는 inline으로
#   ③ 사람이 쓴 값은 반드시 escape()
#   ④ **점수 한계 문구는 접히지 않는다** (R20) — 예산을 넘겨도 남는다

STYLE = (
    "<style>"
    "table{border-collapse:collapse}"
    "td{font-variant-numeric:tabular-nums}"
    f".d{{padding:6px 10px 6px 0;color:{MUTED};white-space:nowrap;vertical-align:top;width:44px}}"
    ".b{padding:6px 0;vertical-align:top;line-height:1.5}"
    f".e{{border-bottom:1px solid {HAIR}}}"
    f".x{{padding:8px 6px;border-bottom:1px solid {PAGE}}}"
    ".r{text-align:right}"
    ".c{text-align:center}"
    f".s{{font-size:11px;letter-spacing:.1em;color:{DIM};font-weight:700;margin-bottom:8px}}"
    ".w{padding:14px 28px 0}"
    ".p{padding:12px 16px 3px}"
    ".t{width:100%;font-size:13px}"
    f".k{{padding:4px 0;color:{SUB};width:56%}}"
    f".v{{padding:4px 0;color:{INK};text-align:right}}"
    f".m{{font-size:12px;color:{MUTED};line-height:1.7}}"
    f".g{{padding:6px 10px;background:{BAND};color:{MUTED}}}"
    ".h{padding:6px 10px}"
    "</style>"
)

GMAIL_CLIP_BYTES = 102_400
# HTML 원본 상한. v3.0에서 카드에 공시 본문 표·수급 표가 늘어 60,000으로는 헐거워졌다 —
# 실측 102,371 bytes로 한계에 29 bytes 남았다 (2026-08-30). 45,000이면 여유가 20% 넘는다.
HTML_BUDGET = 45_000

# 판정 색 (DESIGN G8). 국내 관행상 빨강은 상승이라 **정합만 색 계열을 뺐다** —
# 판정은 등락과 다른 축이다. 불일치는 빨강이 직관적이라 그대로 둔다.
STAND_THEME: dict[str, tuple[str, str]] = {
    "불일치": ("#C9283E", "#FFFFFF"),
    "정합": ("#0F6E5C", "#FFFFFF"),
    "무관": ("", MUTED),  # 배경 없이 테두리만
}

SECTION_AGAINST = "증거가 신호를 거스르는 종목"
SECTION_REST_V3 = "그 밖의 종목"

# **이 문구는 접히지 않는다** (R20·DESIGN G11). 점수는 사실보다 그럴듯해 보인다.
SCORE_LIMIT_NOTE = (
    "근거 점수가 보지 않는 것 — 실적·밸류에이션 · 업황 · 시장 전체 흐름 · 공시 이후의 주가. "
    "점수는 신호의 근거가 얼마나 받쳐지는가를 재며, 종목의 좋고 나쁨이 아닙니다."
)
PAGE_LINK_WORD = "전문 보기 →"
FOLDED_WORDING = "정기·정형 공시 {n}건은 접었습니다"


def _eok(won: int | None) -> str:
    """원 → `1,457억`. None이면 `—`."""
    return "—" if won is None else f"{won // 100_000_000:,}억"


def _eok_signed(won: int | None) -> str:
    """부호 있는 억 단위 — 수급은 방향이 값이다."""
    if won is None:
        return "—"
    return f"{won / 100_000_000:+,.1f}억"


def _money_color(v: int | None) -> str:
    return DIM if v is None or v == 0 else (UP if v > 0 else DOWN)


def _pct(v: float) -> str:
    return f'<span style="color:{UP if v >= 0 else DOWN}">{v:+.2f}%</span>'


def _dot(level: str, size: int = 7) -> str:
    color = THEMES.get(level, THEMES["none"])[0]
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'background:{color}"></span>'
    )


def _stand_chip(stand: str, size: int = 10) -> str:
    """판정 칩 (DESIGN G8)."""
    bg, fg = STAND_THEME.get(stand, ("", MUTED))
    style = (
        f"background:{bg};color:{fg}" if bg else f"border:1px solid #C6CDDE;color:{fg}"
    )
    return (
        f'<span style="display:inline-block;{style};font-size:{size}px;font-weight:700;'
        f'padding:2px 6px">{escape(stand)}</span>'
    )


def _stand_score_chip(v: Verdict) -> str:
    """카드 머리의 `불일치 23점` 칩."""
    bg, fg = STAND_THEME.get(v.stand, ("", MUTED))
    style = f"background:{bg};color:#FFFFFF" if bg else f"border:1px solid #C6CDDE;color:{MUTED}"
    return (
        f'<span style="display:inline-block;{style};font-size:11px;font-weight:700;'
        f'padding:3px 8px">{escape(v.stand)} {v.score}점</span> '
    )


def _score_bar(v: Verdict, width: int = 44) -> str:
    """점수 막대 + 숫자 (DESIGN G9). 숫자만 두면 60과 27의 거리가 눈에 안 들어온다."""
    color = STAND_THEME.get(v.stand, ("", MUTED))[0] or MUTED
    filled = max(0, min(width, round(width * v.score / 100)))
    return (
        f'<table style="width:100%"><tr>'
        f'<td style="width:{width}px;background:{PAGE};height:6px">'
        f'<div style="width:{filled}px;height:6px;background:{color}"></div></td>'
        f'<td style="padding-left:6px;font-size:12px;font-weight:700;color:{color}">'
        f"{v.score}</td></tr></table>"
    )


def _split_disclosures(b: Briefing, cap: int) -> tuple[list[Disclosure], list[Disclosure], int]:
    """공시를 (위험 유형에 걸린 것, 보일 나머지, 생략된 수)로 나눈다.

    **플래그된 공시는 먼저 오고 절대 잘리지 않는다.**
    """
    flagged_nos = {f.rcept_no for f in b.flags}
    flagged = [d for d in b.disclosures if d.rcept_no in flagged_nos]
    plain = [d for d in b.disclosures if d.rcept_no not in flagged_nos]
    return flagged, plain[:cap], max(0, len(plain) - cap)


def _level_of(b: Briefing, rcept_no: str) -> str:
    for f in b.flags:
        if f.rcept_no == rcept_no:
            return f.level
    return ""


def _row(date_cell: str, body: str, *, last: bool = False) -> str:
    e = "" if last else " e"
    return f'<tr><td class="d{e}">{date_cell}</td><td class="b{e}">{body}</td></tr>'


def _chip(text: str, bg: str, fg: str = "#FFFFFF", border: str = "") -> str:
    edge = f"border:1px solid {border};" if border else ""
    return (
        f'<span style="display:inline-block;{edge}background:{bg};color:{fg};font-size:10px;'
        f'font-weight:700;padding:2px 5px">{text}</span>'
    )


def _disclosure_row(b: Briefing, d: Disclosure, *, last: bool = False, tail: str = "") -> str:
    """공시 한 줄 — **제목 자체가 원문 링크다** (N2)."""
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
    day = _md(n.published) if n.published else ""
    body = f'<a href="{escape(n.link)}" style="color:{SUB}">{escape(n.title)}</a>{tail}'
    return _row(day, body, last=last)


def _label(text: str, extra: str = "") -> str:
    more = f' <span style="color:#C6CDDE;font-weight:400">{extra}</span>' if extra else ""
    return f'<div class="s">{text}{more}</div>'


def _more(n: int) -> str:
    return f' <span style="color:{DIM}">· 외 {n}건</span>' if n else ""


def _list(label: str, rows: list[str], extra: str = "") -> str:
    return (
        f'<tr><td class="p">{_label(label, extra)}'
        f'<table width="100%" class="t">{"".join(rows)}</table></td></tr>'
    )


def _excerpt(text: str, cap: int = EXCERPT_LEN) -> str:
    """메일에 실을 발췌 (DESIGN G10). 문장 경계에서 끊는다."""
    body = text.strip()
    if len(body) <= cap:
        return escape(body)
    cut = body[:cap]
    stop = max(cut.rfind("."), cut.rfind("다 "), cut.rfind("다."))
    return escape(cut[: stop + 1] if stop > cap // 2 else cut) + " …"


def _analysis_block(b: Briefing, page_url: str) -> str:
    """분석 발췌 + 전문 링크 (F19·F20·DESIGN G10)."""
    if not b.summary:
        return ""
    link = ""
    if page_url:
        link = (
            f'<div style="margin-top:9px">'
            f'<a href="{escape(page_url)}#{escape(b.ticker)}" style="font-weight:700">'
            f'{PAGE_LINK_WORD}</a> '
            f'<span style="color:{DIM};font-size:12px">{len(b.summary)}자</span></div>'
        )
    return (
        f'<tr><td style="padding:13px 16px 0">'
        f'<div style="background:{BAND};padding:12px 14px;font-size:13px;color:{SUB};'
        f'line-height:1.72">{_excerpt(b.summary)}{link}</div></td></tr>'
    )


def _body_table(b: Briefing) -> str:
    """공시 본문 표 (F15·DESIGN §8). **잠재 물량이 이 표의 핵심이다.**"""
    if not b.bodies:
        return ""
    rows: list[str] = []
    for x in b.bodies:
        funds = " · ".join(f"{escape(k)} {_eok(v)}" for k, v in x.use_of_funds) or "—"
        over = (
            f'<span style="color:{UP};font-weight:700">{x.overhang_pct:.2f}%</span>'
            + (f" ({x.conv_shares:,}주)" if x.conv_shares else "")
            if x.overhang_pct is not None
            else "—"
        )
        rows.append(
            f'<tr><td class="g" style="width:82px">발행금액</td>'
            f'<td class="h" style="font-weight:700">{_eok(x.amount)}</td>'
            f'<td class="g" style="width:82px">자금 용도</td>'
            f'<td class="h">{funds}</td></tr>'
            f'<tr><td class="g">발행 방법</td><td class="h">{escape(x.method) or "—"}</td>'
            f'<td class="g">표면·만기이자</td>'
            f'<td class="h">{_rate(x.coupon_rate)} / {_rate(x.ytm_rate)}</td></tr>'
            f'<tr><td class="g">전환가액</td>'
            f'<td class="h">{f"{x.conv_price:,}원" if x.conv_price else "—"}</td>'
            f'<td style="padding:6px 10px;background:{THEMES["red"][1]};color:{THEMES["red"][3]};'
            f'font-weight:700">잠재 물량</td><td class="h">{over}</td></tr>'
            f'<tr><td class="g">전환청구</td>'
            f'<td class="h">{escape(x.conv_from) or "—"} ~ {escape(x.conv_to) or "—"}</td>'
            f'<td class="g">미상환 잔액</td><td class="h">{_eok(x.outstanding)}</td></tr>'
        )
    return (
        f'<tr><td class="p">{_label("공시 본문")}'
        f'<table width="100%" style="width:100%;font-size:12.5px;border:1px solid {HAIR}">'
        f'{"".join(rows)}</table></td></tr>'
    )


def _rate(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _flows_table(b: Briefing) -> str:
    """수급 30일 요약 + 공시 당일 (F17·DESIGN §8)."""
    if b.flows is None or not b.flows.days:
        return ""
    f = b.flows
    head = (
        f'<tr style="background:{BAND}">'
        f'<td style="padding:5px 8px;color:{MUTED};font-size:11px">　</td>'
        + "".join(
            f'<td class="r" style="padding:5px 8px;color:{MUTED};font-size:11px">{w}</td>'
            for w in ("기관", "외국인", "개인")
        )
        + "</tr>"
    )
    rows = [head, _flow_row("30일 누적", f.inst_total, f.foreign_total, f.indiv_total)]
    flagged_nos = {x.rcept_no for x in b.flags}
    flagged_days = {d.rcept_dt for d in b.disclosures if d.rcept_no in flagged_nos}
    for day in sorted(flagged_days):
        row = f.on(day)
        if row is not None:
            rows.append(
                _flow_row(f"{_md(day)} 공시일", row.inst, row.foreign, row.indiv, mark=True)
            )
    return (
        f'<tr><td class="p">{_label("기관·외국인 수급 30일", "단위 억원")}'
        f'<table width="100%" style="width:100%;font-size:12.5px">{"".join(rows)}</table>'
        f"</td></tr>"
    )


def _flow_row(
    label: str, inst: int | None, foreign: int | None, indiv: int | None, *, mark: bool = False
) -> str:
    bg = f'background:{THEMES["red"][1]}' if mark else ""
    name = (
        f'<td style="padding:6px 8px;color:{THEMES["red"][3]};font-weight:700">{label}</td>'
        if mark
        else f'<td style="padding:6px 8px;border-bottom:1px solid {HAIR};color:{SUB}">{label}</td>'
    )
    edge = "" if mark else f"border-bottom:1px solid {HAIR};"
    cells = "".join(
        f'<td class="r" style="padding:6px 8px;{edge}color:{_money_color(v)}">'
        f"{_eok_signed(v)}</td>"
        for v in (inst, foreign, indiv)
    )
    return f'<tr style="{bg}">{name}{cells}</tr>'


def _parts_line(v: Verdict) -> str:
    """점수가 어떻게 나왔는지 (F18). 숫자만 두면 어디서 왔는지 알 수 없다."""
    if not v.parts:
        return ""
    bits = " ".join(
        f'<span style="color:{UP if p.delta < 0 else "#0F6E5C"}">{p.delta:+d}</span> '
        f"{escape(p.label)}"
        for p in v.parts
    )
    return f'<b style="color:{SUB}">{v.score}점</b> = 중립 {NEUTRAL} {bits}'


def _meta_bar(b: Briefing, v: Verdict | None) -> str:
    """카드 바닥 — 점수 근거 + 참고값 + 생략 표기."""
    bits: list[str] = []
    if b.flow is not None:
        f = b.flow
        bits.append(f'시총 <b style="color:{SUB}">{_eok(f.mktcap)}</b>')
        bits.append(f'{f.days}일 거래대금 <b style="color:{SUB}">{_eok(f.trdval_5d)}</b>')
        bits.append(f'<span style="color:{DIM}">{f.bas_dd[4:6]}/{f.bas_dd[6:8]} 기준</span>')
    if b.anomaly is not None:
        bits.append(f"공시 이상 {b.anomaly.score}/100 {escape(b.anomaly.verdict)}")
    if b.insider is not None and b.insider.sell_cluster:
        i = b.insider
        bits.append(f"임원·주요주주 매도 {i.sell_events}건 · {i.unique_sellers}명")
    parts = _parts_line(v) if v is not None else ""
    note = _skip_note(b)
    if not parts and not bits and not note:
        return ""
    warn = f'<div style="padding-top:6px;color:{DIM}">{escape(note)}</div>' if note else ""
    ref = f'<div style="padding-top:4px;color:{DIM}">{"　".join(bits)}</div>' if bits else ""
    return (
        f'<tr><td style="padding:12px 16px 14px">'
        f'<div class="m" style="border-top:1px solid {HAIR};padding-top:10px">'
        f"{parts}{ref}{warn}</div></td></tr>"
    )


def _verdict_text(b: Briefing) -> str:
    """머리 밴드의 한 줄 — 사실만 (N1 v2)."""
    if b.level == "unknown":
        return UNKNOWN_WORDING
    if b.level == "error":
        return f"{ERROR_WORDING}: {escape(b.error)}" if b.error else ERROR_WORDING
    bits: list[str] = []
    if b.flags:
        kinds = sorted({f.rule for f in b.flags})
        label = FLAG_LABELS.get(kinds[0], kinds[0]) if len(kinds) == 1 else "위험 유형"
        bits.append(f"{escape(label)} {len(b.flags)}건")
    over = sum(x.overhang_pct or 0.0 for x in b.bodies)
    if over:
        bits.append(f"잠재 물량 {over:.2f}%")
    if b.flows is not None and b.flows.days:
        total = sum(v for v in (b.flows.inst_total, b.flows.foreign_total) if v is not None)
        if total:
            bits.append(f"30일 기관·외국인 {'순매수' if total > 0 else '순매도'}")
    if not bits:
        n = len(b.disclosures)
        return f"공시 {n}건　<b>{NONE_WORDING.format(days=b.window_days)}</b>"
    return " · ".join(bits)


def _head_band(b: Briefing, v: Verdict | None, *, compact: bool) -> str:
    """카드 머리 — 종목명 · 종가 · 등락 · 판정 칩 · 한 줄 요약."""
    _d, bg, line, ink = THEMES.get(b.level, THEMES["none"])
    size = 15 if compact else 16
    price = ""
    if b.close:
        mark = f' <span style="color:{DIM};font-size:12px">진행중</span>' if b.in_progress else ""
        price = (
            f'{b.close:,}<span style="font-size:12px;font-weight:400;color:{SUB}">원</span> '
            f"{_pct(b.change_pct)}{mark}"
        )
    chip = _stand_score_chip(v) if v is not None else ""
    pad = "12px 16px 10px" if compact else "14px 16px 12px"
    return (
        f'<tr><td style="padding:{pad};background:{bg};border-bottom:1px solid {line}">'
        f'<table width="100%"><tr>'
        f'<td style="font-size:{size}px;font-weight:800;letter-spacing:-.02em">'
        f'{escape(b.name)} <span style="color:{DIM};font-weight:400;font-size:12px">'
        f"{escape(b.ticker)}</span></td>"
        f'<td class="r" style="font-size:{size - 1}px;font-weight:700">{price}</td></tr></table>'
        f'<div style="margin-top:9px;font-size:{12 if compact else 12.5}px;color:{ink};'
        f'line-height:1.55">{chip}<span style="font-weight:700">{_verdict_text(b)}</span></div>'
        f"</td></tr>"
    )


def _disclosure_block(b: Briefing, cap: int) -> str:
    """공시 목록 + 정형 공시 접기 한 줄 (F16·DESIGN G12)."""
    shown_all, folded = routine.fold(b.disclosures, {f.rcept_no for f in b.flags})
    flagged_nos = {f.rcept_no for f in b.flags}
    flagged = [d for d in shown_all if d.rcept_no in flagged_nos]
    plain = [d for d in shown_all if d.rcept_no not in flagged_nos]
    omitted = max(0, len(plain) - cap)
    shown = flagged + plain[:cap]
    if not shown and not folded:
        return ""
    rows = [
        _disclosure_row(
            b, d, last=(i == len(shown) - 1), tail=_more(omitted) if i == len(shown) - 1 else ""
        )
        for i, d in enumerate(shown)
    ]
    if folded:
        rows.append(
            f'<tr><td colspan="2" style="padding:6px 0 0;color:{DIM};font-size:12px">'
            f"{FOLDED_WORDING.format(n=len(folded))}</td></tr>"
        )
    extra = "— 위험 유형을 먼저 싣습니다" if flagged and plain else ""
    return _list(f"공시 {len(b.disclosures)}건", rows, extra)


def _news_block(b: Briefing, cap: int) -> str:
    if not b.news:
        return ""
    shown = b.news[:cap]
    rest = len(b.news) - len(shown)
    rows = [
        _news_row(n, last=(i == len(shown) - 1), tail=_more(rest) if i == len(shown) - 1 else "")
        for i, n in enumerate(shown)
    ]
    return _list("같은 기간 뉴스", rows)


def _card(b: Briefing, v: Verdict | None, page_url: str, *, lean: bool = False) -> str:
    """전체 카드 — 증거가 신호를 거스르는 종목.

    `lean`이면 수급 표와 뉴스를 뺀다 (예산 마지막 단계). 둘 다 전문 페이지에 그대로 있고,
    **판정·공시·본문 표·점수는 어느 경우에도 남는다** — 그것이 이 카드의 존재 이유다.
    """
    dot, _bg, line, _ink = THEMES.get(b.level, THEMES["none"])
    edge = STAND_THEME.get(v.stand, ("", ""))[0] if v is not None else ""
    extra = "" if lean else f"{_flows_table(b)}{_news_block(b, COMPACT_NEWS)}"
    return (
        f'<tr><td class="w"><table width="100%" '
        f'style="width:100%;border:1px solid {line};border-left:4px solid {edge or dot}">'
        f"{_head_band(b, v, compact=False)}"
        f"{_analysis_block(b, page_url)}"
        f"{_disclosure_block(b, PLAIN_DISCLOSURES)}"
        f"{_body_table(b)}{extra}"
        f"{_meta_bar(b, v)}</table></td></tr>"
    )


def _card_compact(b: Briefing, v: Verdict | None, page_url: str) -> str:
    """압축 카드 — 정합·무관 종목."""
    _d, _bg, line, _ink = THEMES.get(b.level, THEMES["none"])
    return (
        f'<tr><td class="w"><table width="100%" style="width:100%;border:1px solid {line}">'
        f"{_head_band(b, v, compact=True)}"
        f"{_analysis_block(b, page_url)}"
        f"{_disclosure_block(b, COMPACT_DISCLOSURES)}"
        f"{_news_block(b, COMPACT_NEWS)}"
        f"{_meta_bar(b, v)}</table></td></tr>"
    )


def _index_table(briefings: Sequence[Briefing], verdicts: dict[str, Verdict]) -> str:
    """인덱스 표 — **전 종목을 한 번에 훑는 유일한 자리다** (DESIGN §8).

    v2.1에 판정·근거점수·30일 수급 세 열이 늘었다. 아래 카드가 예산 때문에 접혀도
    **모든 종목은 이 표에 남는다.**
    """
    if not briefings:
        return ""
    th = (
        f"padding:7px 6px;font-size:11px;color:{MUTED};font-weight:700;"
        f"border-bottom:1px solid {LINE}"
    )
    head = f'<td style="{th};padding-left:8px">종목</td>'
    columns = (("등락", "r"), ("판정", "c"), ("근거 점수", ""), ("공시", "r"), ("30일 수급", "r"))
    for name, cls in columns:
        head += f'<td class="{cls}" style="{th}">{name}</td>'
    rows = [f'<tr style="background:{BAND}">{head}</tr>']
    for b in briefings:
        v = verdicts.get(b.ticker)
        against = v is not None and v.stand == "불일치"
        bg = f' style="background:{THEMES["red"][1]}"' if against else ""
        edge = THEMES["red"][0] if against else "#FFFFFF"
        w = ' style="font-weight:700"' if against else ""
        if b.level in ("unknown", "error"):
            count = f'<span style="color:{DIM}">—</span>'
        elif b.flags:
            count = (
                f'<b style="color:{THEMES[b.level][0]}">{len(b.flags)}</b>'
                f'<span style="color:{DIM}">/{len(b.disclosures)}</span>'
            )
        else:
            count = f'<span style="color:{DIM}">0/{len(b.disclosures)}</span>'
        flow = (
            _eok_signed(_net(b))
            if b.flows is not None and b.flows.days
            else f'<span style="color:{DIM}">—</span>'
        )
        rows.append(
            f"<tr{bg}>"
            f'<td class="x"{w} style="padding-left:8px;border-left:3px solid {edge};'
            f'border-bottom:1px solid {PAGE}">{escape(b.name)} '
            f'<span style="color:{DIM};font-weight:400;font-size:11px">'
            f"{escape(b.ticker)}</span></td>"
            f'<td class="x r"{w}>{_pct(b.change_pct) if b.close else "—"}</td>'
            f'<td class="x c">{_stand_chip(v.stand) if v is not None else "—"}</td>'
            f'<td class="x" style="width:76px">{_score_bar(v) if v is not None else "—"}</td>'
            f'<td class="x r">{count}</td>'
            f'<td class="x r" style="padding-right:8px;color:{_money_color(_net(b))}">{flow}</td>'
            f"</tr>"
        )
    return (
        f'<tr><td style="padding:22px 28px 4px">'
        f'<div style="font-size:11px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"한눈에 보기</div></td></tr>"
        f'<tr><td style="padding:8px 28px 6px">'
        f'<table width="100%" class="t">{"".join(rows)}</table></td></tr>'
        f"{_score_limit_block()}"
    )


def _net(b: Briefing) -> int | None:
    """30일 기관+외국인 합. 인덱스 표의 수급 칸."""
    if b.flows is None or not b.flows.days:
        return None
    got = [v for v in (b.flows.inst_total, b.flows.foreign_total) if v is not None]
    return sum(got) if got else None


def _score_limit_block() -> str:
    """**접히지 않는 문구** (R20·DESIGN G11). 인덱스 표 바로 아래."""
    head, tail = SCORE_LIMIT_NOTE.split(" — ", 1)
    return (
        f'<tr><td style="padding:4px 28px 22px">'
        f'<div style="padding:10px 12px;background:{BAND};font-size:11.5px;color:{MUTED};'
        f'line-height:1.65"><b style="color:{SUB}">{head}</b> — {tail}</div></td></tr>'
    )


def _section(title: str, n: int, color: str, note: str = "") -> str:
    sub = f'<div style="margin-top:6px;font-size:12px;color:{DIM}">{note}</div>' if note else ""
    return (
        f'<tr><td style="padding:26px 28px 0">'
        f'<div style="border-top:1px solid {LINE};padding-top:20px">'
        f'<span style="display:inline-block;width:9px;height:9px;background:{color}"></span>'
        f'<span style="margin-left:8px;font-size:14px;font-weight:800">{title}</span> '
        f'<span style="color:{DIM};font-size:13px">{n}</span>{sub}</div></td></tr>'
    )


def _shell(inner: str) -> str:
    return (
        f'{STYLE}<table width="100%" style="width:100%;background:{PAGE};'
        f'font-family:{FONT};color:{INK}">'
        f'<tr><td style="padding:20px 10px">'
        f'<table width="600" align="center" style="width:600px;max-width:600px;'
        f'background:#FFFFFF;border:1px solid {LINE}">{inner}</table></td></tr></table>'
    )


def _header(
    briefings: Sequence[Briefing], data_date: date, verdicts: dict[str, Verdict], err: str
) -> str:
    """머리 — 날짜 · 한 문장 · 판정 칩."""
    counts: dict[str, int] = {}
    for b in briefings:
        v = verdicts.get(b.ticker)
        if v is not None:
            counts[v.stand] = counts.get(v.stand, 0) + 1
    cells = ""
    for i, stand in enumerate(("불일치", "정합", "무관")):
        if not counts.get(stand):
            continue
        bg, fg = STAND_THEME[stand]
        if i:
            cells += '<td style="width:6px"></td>'
        cells += (
            f'<td style="background:{bg or PAGE};color:{fg if bg else SUB};font-size:12px;'
            f'font-weight:700;padding:5px 11px">{stand} {counts[stand]}</td>'
        )
    warn = (
        f'<div class="m" style="margin-top:12px">⚠ 근거 서술 생략 — '
        f'판정과 근거 자료는 그대로 있습니다'
        f" ({escape(err)})</div>"
        if err
        else ""
    )
    days = briefings[0].window_days if briefings else 30
    return (
        f'<tr><td style="padding:26px 28px 20px;border-bottom:3px solid {INK}">'
        f'<div style="font-size:12px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"신호 검증 브리핑 · {data_date.year}. {data_date.month:02d}. {data_date.day:02d}</div>"
        f'<div style="font-size:23px;font-weight:800;letter-spacing:-.02em;margin-top:8px;'
        f'line-height:1.3">신호 {len(briefings)}건이 근거를 갖는지 확인했습니다</div>'
        f'<div style="margin-top:6px;font-size:12px;color:{DIM}">'
        f'최근 {days}일 공시·뉴스·수급 기준</div>'
        f'<table style="margin-top:14px"><tr>{cells}</tr></table>{warn}</td></tr>'
    )


def _footer() -> str:
    """꼬리 — 한계 문구 (R7·R20). **여기는 절대 지우지 않는다.**"""
    return (
        f'<tr><td style="padding:26px 28px">'
        f'<div class="m" style="border-top:3px solid {INK};padding-top:14px">'
        f'이 메일은 신호의 근거를 확인한 결과입니다. <b style="color:{SUB}">{LIMIT_NOTE}</b><br>'
        f"{SCORE_LIMIT_NOTE} 공시 원문은 금융감독원 전자공시시스템(DART)에서 확인할 수 있습니다."
        f"</div></td></tr>"
    )


def _empty(day: str, message: str) -> str:
    return _shell(
        f'<tr><td style="padding:30px 28px;border-bottom:3px solid {INK}">'
        f'<div style="font-size:12px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"신호 검증 브리핑 · {day}</div>"
        f'<div style="font-size:20px;font-weight:800;margin-top:8px">{escape(message)}</div>'
        f'</td></tr><tr><td style="padding:22px 28px 26px">'
        f'<div class="m">{LIMIT_NOTE}</div></td></tr>'
    )


def _build(
    briefings: Sequence[Briefing],
    data_date: date,
    verdicts: dict[str, Verdict],
    page_url: str,
    summary_error: str,
    cards: int,
    lean: bool = False,
    against_cards: int | None = None,
) -> str:
    """본문 한 벌. `cards`는 압축 카드를 몇 종목까지 펼칠지 — 예산 맞추기용.

    `lean`이면 거스르는 종목 카드에서도 수급 표·뉴스를 뺀다 (마지막 단계).
    """
    against = [b for b in briefings if _stand_of(b, verdicts) == "불일치"]
    rest = [b for b in briefings if _stand_of(b, verdicts) != "불일치"]
    parts = [_header(briefings, data_date, verdicts, summary_error),
             _index_table(briefings, verdicts)]
    if against:
        shown_against = against if against_cards is None else against[:against_cards]
        parts.append(_section(SECTION_AGAINST, len(against), THEMES["red"][0]))
        parts.extend(
            _card(b, verdicts.get(b.ticker), page_url, lean=lean) for b in shown_against
        )
        if len(against) > len(shown_against):
            parts.append(
                f'<tr><td class="w"><div class="m" style="border:1px dashed {THEMES["red"][2]};'
                f'padding:13px 16px;text-align:center;color:{THEMES["red"][3]}">'
                f"거스르는 종목 {len(against) - len(shown_against)}건은 카드를 접었습니다 — "
                f"판정과 점수는 위 「한눈에 보기」 표에, 전문은 페이지에 있습니다</div></td></tr>"
            )
    if rest:
        shown = rest[:cards]
        parts.append(_section(SECTION_REST_V3, len(rest), "#C6CDDE"))
        parts.extend(_card_compact(b, verdicts.get(b.ticker), page_url) for b in shown)
        if len(rest) > len(shown):
            parts.append(
                f'<tr><td class="w"><div class="m" style="border:1px dashed {LINE};'
                f'padding:13px 16px;text-align:center">나머지 {len(rest) - len(shown)}종목은 '
                f"위 「한눈에 보기」 표에 있습니다 — 메일 길이를 넘지 않으려 카드를 접었습니다"
                f"</div></td></tr>"
            )
    if lean and against:
        parts.append(
            f'<tr><td class="w"><div class="m" style="border:1px dashed {LINE};'
            f'padding:13px 16px;text-align:center">수급 표와 뉴스는 전문 페이지에 있습니다 — '
            f"메일 길이를 넘지 않으려 뺐습니다</div></td></tr>"
        )
    parts.append(_footer())
    return _shell("".join(parts))


def _stand_of(b: Briefing, verdicts: dict[str, Verdict]) -> str:
    v = verdicts.get(b.ticker)
    return v.stand if v is not None else "무관"


def html(
    briefings: Sequence[Briefing],
    data_date: date,
    *,
    verdicts: dict[str, Verdict] | None = None,
    page_url: str = "",
    stale: bool = False,
    summary_error: str = "",
) -> str:
    """HTML 본문 (F7 v3 · DESIGN §8).

    인덱스 표(판정·점수·수급) → 거스르는 종목 전체 카드 → 그 밖 압축 카드.

    **예산을 넘으면 압축 카드부터 접는다.** 인덱스 표·거스르는 종목 카드·
    **점수 한계 문구**는 접지 않는다 — 접을 것과 접지 않을 것의 우선순위가 곧 설계다 (R20).

    Args:
        briefings: 브리핑 목록 (순서는 호출자가 정한다).
        data_date: 데이터 기준일.
        verdicts: `{ticker: Verdict}` — 코드가 낸 판정 (F18). 없으면 판정 열이 빈다.
        page_url: 전문 페이지 주소 (F20). 없으면 링크를 달지 않는다.
        stale: 상위 배치가 데이터 지연으로 신호를 만들지 않았는가.
        summary_error: 근거 서술 실패 사유.
    """
    day = _md(data_date)
    if stale:
        return _empty(day, "신호 배치가 데이터 지연으로 신호를 만들지 않았습니다")
    if not briefings:
        return _empty(day, "오늘 신호가 없습니다")

    vs = verdicts or {}
    rest_n = sum(1 for b in briefings if _stand_of(b, vs) != "불일치")
    # ① 압축 카드를 뒤에서부터 접는다
    for cards in range(rest_n, -1, -1):
        doc = _build(briefings, data_date, vs, page_url, summary_error, cards)
        if len(doc) <= HTML_BUDGET:
            return doc + "\n"
    # ② 그래도 넘으면 거스르는 종목 카드에서 수급 표·뉴스를 뺀다 (둘 다 전문 페이지에 있다).
    doc = _build(briefings, data_date, vs, page_url, summary_error, 0, lean=True)
    if len(doc) <= HTML_BUDGET:
        return doc + "\n"
    # ③ 마지막 — 거스르는 종목 카드도 뒤에서부터 접는다. 15종목이 전부 불일치면
    #    전체 카드로는 물리적으로 들어가지 않는다. **잘려서 꼬리 문구가 사라지는 것보다 낫다.**
    #    인덱스 표에는 판정·점수가 전부 남고, 전문 페이지에는 모든 것이 남는다 (R20).
    against_n = sum(1 for b in briefings if _stand_of(b, vs) == "불일치")
    for n in range(against_n - 1, 0, -1):
        doc = _build(briefings, data_date, vs, page_url, summary_error, 0, True, n)
        if len(doc) <= HTML_BUDGET:
            return doc + "\n"
    return _build(briefings, data_date, vs, page_url, summary_error, 0, True, 1) + "\n"
