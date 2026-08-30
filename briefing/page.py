"""전문 페이지 생성 (SPEC F20 · DESIGN §8) — 순수 함수.

메일에는 발췌 2~3줄만 싣고 전문은 여기로 보낸다. **15종목 × 2,000자 = 30,000자는
UTF-8 90KB로 Gmail 클리핑 한계(102,400 bytes)를 넘는다** (D20·N15).

담는 것: 목차 → 종목마다 **분석 전문 + 근거 자료 전부**
(공시 본문 표 · 수급 30거래일 · 뉴스 제목과 요약 · 검증한 차트 조건).

## 이 페이지는 본인 전용이다 (R7 v2)

판정과 점수를 남에게 배포하면 유사투자자문업 신고 대상이 된다.
- 머리에 **"링크를 공유하지 마세요"**를 띄운다.
- 종목마다 점수 한계 문구를 한 번 더 적는다 (R20).
- 발행 쪽(`notify`·워크플로)이 **공개 링크로 만들지 않는다** — 이 모듈은 문자열만 만든다.

이 모듈은 네트워크도 DB도 모른다. 실패는 호출자 몫이고, 페이지가 없어도 메일은 간다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from briefing.models import Briefing, EventBody, dart_link
from briefing.render import (
    BAND,
    DIM,
    FONT,
    HAIR,
    INK,
    LIMIT_NOTE,
    LINE,
    MUTED,
    PAGE,
    SCORE_LIMIT_NOTE,
    STAND_THEME,
    SUB,
    THEMES,
    UP,
)
from briefing.verdict import NEUTRAL, Verdict

WIDTH = 820
PRIVATE_NOTE = (
    "본인 전용 페이지입니다. 링크를 공유하지 마세요 — "
    "판정과 점수를 남에게 배포하면 유사투자자문업 신고 대상이 됩니다."
)
TITLE = "신호 검증 브리핑 · 전문"
FLOW_ROWS = 30  # 표에 보일 거래일 수


def _md(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}"


def _eok(won: int | None) -> str:
    return "—" if won is None else f"{won // 100_000_000:,}억"


def _eok_signed(won: int | None) -> str:
    return "—" if won is None else f"{won / 100_000_000:+,.1f}억"


def _stand_color(stand: str) -> str:
    return STAND_THEME.get(stand, ("", MUTED))[0] or MUTED


def _rate(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


def _color(v: int | None) -> str:
    return DIM if v is None or v == 0 else (UP if v > 0 else "#1F63A8")


def _stand_style(stand: str) -> str:
    bg = STAND_THEME.get(stand, ("", ""))[0]
    return f"background:{bg};color:#FFFFFF" if bg else f"border:1px solid #C6CDDE;color:{MUTED}"


def _anchor(ticker: str) -> str:
    """종목 링크의 앵커. 메일의 `전문 보기 →`가 `#{ticker}`로 온다."""
    return escape(ticker)


def _head(briefings: Sequence[Briefing], data_date: date, verdicts: dict[str, Verdict]) -> str:
    counts: dict[str, int] = {}
    for b in briefings:
        v = verdicts.get(b.ticker)
        if v is not None:
            counts[v.stand] = counts.get(v.stand, 0) + 1
    summary = " · ".join(f"{k} {v}" for k, v in counts.items()) or "대상 없음"
    y, m, d = data_date.year, data_date.month, data_date.day
    return (
        f'<div style="padding:30px 36px 22px;border-bottom:3px solid {INK}">'
        f'<div style="font-size:12px;letter-spacing:.14em;color:{MUTED};font-weight:700">'
        f"{TITLE} · {y}. {m:02d}. {d:02d}</div>"
        f'<div style="font-size:26px;font-weight:800;letter-spacing:-.02em;margin-top:8px">'
        f"신호 {len(briefings)}건 · {summary}</div>"
        f'<div style="margin-top:12px;padding:9px 12px;background:{THEMES["amber"][1]};'
        f'border:1px solid {THEMES["amber"][2]};font-size:12px;color:{THEMES["amber"][3]};'
        f'line-height:1.6">{PRIVATE_NOTE}</div></div>'
    )


def _toc(briefings: Sequence[Briefing], verdicts: dict[str, Verdict]) -> str:
    rows: list[str] = []
    for b in briefings:
        v = verdicts.get(b.ticker)
        chip = (
            f'<span style="display:inline-block;{_stand_style(v.stand)};font-size:10px;'
            f'font-weight:700;padding:2px 6px">{escape(v.stand)}</span>'
            if v is not None
            else ""
        )
        color = STAND_THEME.get(v.stand, ("", MUTED))[0] or MUTED if v is not None else MUTED
        rows.append(
            f'<tr><td style="padding:7px 8px;border-bottom:1px solid {HAIR}">{chip} '
            f'<a href="#{_anchor(b.ticker)}" style="margin-left:8px;font-weight:700;'
            f'color:{INK}">{escape(b.name)}</a> '
            f'<span style="color:{DIM};font-size:12px">{escape(b.ticker)}</span></td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid {HAIR};text-align:right;'
            f'color:{color};font-weight:700">{v.score if v is not None else "—"}점</td>'
            f'<td style="padding:7px 8px;border-bottom:1px solid {HAIR};text-align:right;'
            f'color:{DIM};font-size:12px">{len(b.summary or "")}자</td></tr>'
        )
    return (
        f'<div style="padding:20px 36px 8px">'
        f'<div style="font-size:11px;letter-spacing:.14em;color:{MUTED};font-weight:700;'
        f'margin-bottom:10px">목차</div>'
        f'<table width="100%" style="width:100%;font-size:13.5px;border-collapse:collapse">'
        f'{"".join(rows)}</table></div>'
    )


def _parts(v: Verdict) -> str:
    if not v.parts:
        return ""
    bits = " ".join(
        f'<span style="color:{UP if p.delta < 0 else "#0F6E5C"}">{p.delta:+d}</span> '
        f"{escape(p.label)}"
        for p in v.parts
    )
    return (
        f'<div style="margin-top:14px;padding:12px 14px;background:{BAND};font-size:12.5px;'
        f'color:{MUTED};line-height:1.9">중립 {NEUTRAL} {bits} → '
        f'<b style="color:{_stand_color(v.stand)}">{v.score}점</b></div>'
    )


def _bodies(bodies: Sequence[EventBody]) -> str:
    """공시 본문 표. **합계 행에 잠재 물량 누계**를 둔다 — 여러 건이면 그것이 핵심이다."""
    if not bodies:
        return ""
    head = "".join(
        f'<td style="padding:7px 10px;color:{MUTED};font-size:11px">{w}</td>'
        for w in ("공시", "금액", "자금 용도", "방법·이자", "전환가")
    )
    rows = [
        f'<tr style="background:{BAND}">{head}'
        f'<td style="padding:7px 10px;color:{MUTED};font-size:11px;text-align:right">'
        f"잠재 물량</td></tr>"
    ]
    for x in bodies:
        funds = " · ".join(f"{escape(k)} {_eok(w)}" for k, w in x.use_of_funds) or "—"
        over = f"{x.overhang_pct:.2f}%" if x.overhang_pct is not None else "—"
        rows.append(
            f'<tr><td style="padding:8px 10px;border-top:1px solid {HAIR}">'
            f'<a href="{dart_link(x.rcept_no)}">{escape(x.decided_on) or "원문"}</a></td>'
            f'<td style="padding:8px 10px;border-top:1px solid {HAIR};font-weight:700">'
            f"{_eok(x.amount)}</td>"
            f'<td style="padding:8px 10px;border-top:1px solid {HAIR}">{funds}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid {HAIR}">'
            f'{escape(x.method) or "—"} · {_rate(x.coupon_rate)}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid {HAIR}">'
            f'{f"{x.conv_price:,}원" if x.conv_price else "—"}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid {HAIR};text-align:right;'
            f'color:{UP};font-weight:700">{over}</td></tr>'
        )
    total = sum(x.overhang_pct or 0.0 for x in bodies)
    outstanding = next((x.outstanding for x in bodies if x.outstanding is not None), None)
    if len(bodies) > 1 or outstanding is not None:
        note = f" · 미상환 CB 잔액 {_eok(outstanding)}" if outstanding is not None else ""
        rows.append(
            f'<tr style="background:{THEMES["red"][1]}">'
            f'<td colspan="5" style="padding:8px 10px;border-top:1px solid {THEMES["red"][2]};'
            f'color:{THEMES["red"][3]};font-weight:700">합계{note}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid {THEMES["red"][2]};'
            f'text-align:right;color:{UP};font-weight:800">{total:.2f}%</td></tr>'
        )
    return _section("근거 — 공시 본문", f'<table width="100%" style="width:100%;font-size:13px;'
                    f'border:1px solid #E1E6F0;border-collapse:collapse">{"".join(rows)}</table>')


def _flows(b: Briefing) -> str:
    """수급 30거래일. 플래그된 공시가 난 날을 강조한다."""
    if b.flows is None or not b.flows.days:
        return ""
    flagged_nos = {f.rcept_no for f in b.flags}
    marked = {d.rcept_dt: d.report_nm for d in b.disclosures if d.rcept_no in flagged_nos}
    head = "".join(
        f'<td style="padding:6px 8px;color:{MUTED};font-size:11px;'
        f'{"text-align:right" if w != "날짜" and w != "비고" else ""}">{w}</td>'
        for w in ("날짜", "기관", "외국인", "개인", "비고")
    )
    rows = [f'<tr style="background:{BAND}">{head}</tr>']
    for day in reversed(b.flows.recent(FLOW_ROWS).days):
        hit = marked.get(day.d)
        bg = f'background:{THEMES["red"][1]}' if hit else ""
        cells = "".join(
            f'<td style="padding:6px 8px;border-top:1px solid {HAIR};text-align:right;'
            f'color:{_color(v)}">{_eok_signed(v)}</td>'
            for v in (day.inst, day.foreign, day.indiv)
        )
        note = (
            f'<span style="color:{THEMES["red"][3]};font-size:11.5px">{escape(hit)}</span>'
            if hit
            else ""
        )
        rows.append(
            f'<tr style="{bg}"><td style="padding:6px 8px;border-top:1px solid {HAIR};'
            f'{"font-weight:700" if hit else ""}">{_md(day.d)}</td>{cells}'
            f'<td style="padding:6px 8px;border-top:1px solid {HAIR}">{note}</td></tr>'
        )
    return _section(
        "근거 — 기관·외국인 수급 30거래일 (단위 억원)",
        f'<table width="100%" style="width:100%;font-size:12.5px;border-collapse:collapse">'
        f'{"".join(rows)}</table>',
    )


def _news(b: Briefing) -> str:
    if not b.news:
        return ""
    rows: list[str] = []
    for n in b.news:
        day = _md(n.published) if n.published else ""
        body = (
            f'<a href="{escape(n.link)}" style="font-weight:700;color:{INK}">'
            f"{escape(n.title)}</a>"
        )
        if n.summary:
            body += (
                f'<div style="color:{MUTED};font-size:12.5px;margin-top:3px">'
                f"{escape(n.summary)}</div>"
            )
        rows.append(
            f'<tr><td style="padding:8px 10px 8px 0;color:{MUTED};white-space:nowrap;'
            f'vertical-align:top;width:46px;border-bottom:1px solid {HAIR}">{day}</td>'
            f'<td style="padding:8px 0;vertical-align:top;line-height:1.6;'
            f'border-bottom:1px solid {HAIR}">{body}</td></tr>'
        )
    return _section(
        f"근거 — 뉴스 {len(b.news)}건",
        f'<table width="100%" style="width:100%;font-size:13px;border-collapse:collapse">'
        f'{"".join(rows)}</table>',
    )


def _conditions(b: Briefing) -> str:
    """검증한 차트 신호 — 상위가 보낸 조건 그대로."""
    if not b.conditions:
        return ""
    rows = "".join(
        f'<tr style="{f"background:{BAND}" if i % 2 else ""}">'
        f'<td style="padding:5px 0;color:{SUB};width:60%">'
        f'{"" if ok else "미충족 "}{escape(label)}</td>'
        f'<td style="padding:5px 0;text-align:right">{escape(actual)}</td></tr>'
        for i, (label, ok, actual) in enumerate(b.conditions)
    )
    return _section(
        f"검증한 차트 신호 — {escape(b.strategy)}",
        f'<table width="100%" style="width:100%;font-size:12.5px;border-collapse:collapse">'
        f"{rows}</table>",
    )


def _section(title: str, body: str) -> str:
    return (
        f'<div style="margin-top:20px">'
        f'<div style="font-size:11px;letter-spacing:.14em;color:{MUTED};font-weight:700;'
        f'margin-bottom:10px">{title}</div>{body}</div>'
    )


def _stock(b: Briefing, v: Verdict | None) -> str:
    """종목 하나 — 분석 전문 + 근거 자료 전부."""
    price = ""
    if b.close:
        color = UP if b.change_pct >= 0 else "#1F63A8"
        price = (
            f'{b.close:,}<span style="font-size:12px;font-weight:400;color:{SUB}">원</span> '
            f'<span style="color:{color}">{b.change_pct:+.2f}%</span>'
        )
    chip = ""
    if v is not None:
        color = STAND_THEME.get(v.stand, ("", MUTED))[0] or MUTED
        filled = max(0, min(120, round(120 * v.score / 100)))
        chip = (
            f'<table style="margin-top:12px;border-collapse:collapse"><tr>'
            f'<td style="{_stand_style(v.stand)};font-size:13px;font-weight:700;'
            f'padding:6px 12px">{escape(v.stand)}</td>'
            f'<td style="padding-left:12px"><table style="border-collapse:collapse"><tr>'
            f'<td style="width:120px;background:{PAGE};height:8px">'
            f'<div style="width:{filled}px;height:8px;background:{color}"></div></td>'
            f'<td style="padding-left:8px;font-size:15px;font-weight:800;color:{color}">'
            f"{v.score}</td>"
            f'<td style="padding-left:4px;font-size:12px;color:{DIM}">/ 100</td>'
            f"</tr></table></td></tr></table>"
        )
    body = (
        f'<div style="margin-top:18px;font-size:14.5px;line-height:1.85;color:#232B42">'
        f"{escape(b.summary)}</div>"
        if b.summary
        else f'<div style="margin-top:18px;font-size:13px;color:{DIM}">근거 서술이 없습니다.</div>'
    )
    limit = (
        f'<div style="margin-top:22px;padding:12px 14px;background:{BAND};font-size:12px;'
        f'color:{MUTED};line-height:1.7">{SCORE_LIMIT_NOTE}</div>'
    )
    return (
        f'<div id="{_anchor(b.ticker)}" style="padding:26px 36px 0">'
        f'<div style="border-top:1px solid {LINE};padding-top:24px">'
        f'<table width="100%" style="border-collapse:collapse"><tr>'
        f'<td><span style="font-size:22px;font-weight:800;letter-spacing:-.02em">'
        f"{escape(b.name)}</span>"
        f'<span style="color:{DIM};font-size:13px;margin-left:6px">{escape(b.ticker)} · '
        f"{escape(b.strategy)}</span></td>"
        f'<td style="text-align:right;font-size:16px;font-weight:700">{price}</td>'
        f"</tr></table>{chip}"
        f"{_parts(v) if v is not None else ''}{body}"
        f"{_bodies(b.bodies)}{_flows(b)}{_news(b)}{_conditions(b)}{limit}</div></div>"
    )


def render(
    briefings: Sequence[Briefing],
    data_date: date,
    verdicts: dict[str, Verdict] | None = None,
) -> str:
    """전문 페이지 한 장 (F20).

    Args:
        briefings: 브리핑 목록 (순서는 호출자가 정한다 — 메일과 같은 순서).
        data_date: 데이터 기준일.
        verdicts: `{ticker: Verdict}`.

    Returns:
        완성된 HTML 문자열. **네트워크를 모른다** — 발행은 호출자 몫이다.
    """
    vs = verdicts or {}
    stocks = "".join(_stock(b, vs.get(b.ticker)) for b in briefings)
    foot = (
        f'<div style="padding:30px 36px 40px">'
        f'<div style="border-top:3px solid {INK};padding-top:14px;font-size:12px;'
        f'color:{MUTED};line-height:1.75">'
        f'이 페이지는 신호의 근거를 확인한 결과입니다. <b style="color:{SUB}">{LIMIT_NOTE}</b><br>'
        f"본인 전용 — 링크를 공유하지 마세요.</div></div>"
    )
    return (
        f"<style>body{{margin:0;background:{PAGE};font-family:{FONT};color:{INK}}}"
        f"a{{color:#1F63A8;text-decoration:none}}a:hover{{text-decoration:underline}}"
        f"table{{border-collapse:collapse}}td{{font-variant-numeric:tabular-nums}}</style>"
        f'<div style="max-width:{WIDTH}px;margin:0 auto;background:#FFFFFF">'
        f"{_head(briefings, data_date, vs)}{_toc(briefings, vs)}{stocks}{foot}</div>\n"
    )
