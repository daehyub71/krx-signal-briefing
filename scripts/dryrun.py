"""과거 신호에 DART 판정을 붙여 본다 — 발송·저장·LLM 없음 (M1 완료 기준).

    python scripts/dryrun.py                    # 최근 90일(≈60거래일) 신호 전부
    python scripts/dryrun.py --limit 30         # 빠른 확인
    python scripts/dryrun.py --out docs/dryrun_m1.md

측정하는 것: 등급 분포(전체·전략별) · unknown 비율 · 오류·020 발생 · 하루 예상 호출 수 ·
걸린 규칙 상위. 🔴 전 건을 원문 링크와 함께 보고서에 적는다 — 손으로 대조하기 위해서다 (SPEC §9-2).

호출은 **종목당 1회**다: 그 종목의 신호일 범위를 덮는 창을 한 번 받아 신호마다 30일 창으로
잘라 판정한다. 운영(하루 15건 × 1회)과 창 계산이 같으므로 결과도 같다.
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from briefing import config, corp, dart, flags, store  # noqa: E402
from briefing.models import WINDOW_DAYS, Disclosure, SignalRow, dart_link  # noqa: E402

STRATEGY_LABELS = {
    "mtf": "MTF 정배열",
    "pullback": "주봉 눌림목",
    "vcp": "VCP 수축",
    "squeeze": "밴드 스퀴즈",
    "turnaround": "장기 턴어라운드",
}


def window_of(signal_d: date) -> tuple[date, date]:
    """운영과 같은 창 — 브리핑은 신호일 다음 날 아침에 돈다: end = d+1, bgn = end−30."""
    end = signal_d + timedelta(days=1)
    return end - timedelta(days=WINDOW_DAYS), end


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0915 — 보고서 스크립트
    """드라이런을 돌리고 보고서를 쓴다."""
    p = argparse.ArgumentParser(prog="dryrun")
    p.add_argument("--days", type=int, default=90, help="신호 조회 범위(달력일). 90 ≈ 60거래일")
    p.add_argument("--limit", type=int, default=0, help="신호 수 상한 (0=전부)")
    p.add_argument("--pause", type=float, default=0.1)
    p.add_argument("--out", default="docs/dryrun_m1.md")
    args = p.parse_args(argv)
    config.load_env()

    today = date.today()
    c = store.conn()
    try:
        signals = store.fetch_signal_rows_since(c, today - timedelta(days=args.days))
    finally:
        store.close()
    if args.limit:
        signals = signals[: args.limit]
    days = sorted({s.d for s in signals})
    per_day = len(signals) / max(len(days), 1)
    print(f"[signals] {len(signals)}건 · {len(days)}거래일 · 하루 평균 {per_day:.1f}건")

    codes = corp.parse_corp_codes(dart.fetch_corp_codes())

    # 종목당 1회 — 신호일 범위를 덮는 창
    by_ticker: dict[str, list[SignalRow]] = collections.defaultdict(list)
    for s in signals:
        by_ticker[s.ticker].append(s)
    cache: dict[str, list[Disclosure] | Exception] = {}
    calls = rate_limited = 0
    for i, (ticker, rows) in enumerate(by_ticker.items(), 1):
        code = codes.get(ticker)
        if code is None:
            continue
        bgn = window_of(min(r.d for r in rows))[0]
        end = window_of(max(r.d for r in rows))[1]
        try:
            cache[ticker] = dart.fetch_disclosures(code, bgn, end)
        except dart.DartRateLimitError as exc:
            rate_limited += 1
            cache[ticker] = exc
        except dart.DartError as exc:
            cache[ticker] = exc
        calls += 1
        if i % 25 == 0:
            print(f"  {i}/{len(by_ticker)} 종목 조회")
        time.sleep(args.pause)

    # 신호마다 30일 창으로 잘라 판정
    levels: collections.Counter[str] = collections.Counter()
    by_strategy: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    rules: collections.Counter[str] = collections.Counter()
    reds: list[tuple[SignalRow, str, str, str]] = []
    ambers: list[tuple[SignalRow, str, str]] = []
    for s in signals:
        if s.ticker not in codes:
            level = "unknown"
        elif isinstance(cache.get(s.ticker), Exception):
            level = "error"
        else:
            bgn, end = window_of(s.d)
            items = [d for d in cache[s.ticker] if bgn <= d.rcept_dt <= end]  # type: ignore[union-attr]
            v = flags.classify(items, company_name=s.name)
            level = v.level
            for f in v.flags:
                rules[f.rule] += 1
                if f.level == "red":
                    reds.append((s, f.rule, f.report_nm, dart_link(f.rcept_no)))
                else:
                    ambers.append((s, f.rule, f.report_nm))
        levels[level] += 1
        by_strategy[s.strategy][level] += 1

    n = len(signals)

    def pct(k: str) -> str:
        return f"{levels[k]} ({levels[k] / max(n, 1):.0%})"

    lines = [
        f"# 드라이런 M1 — {today}",
        "",
        f"> 최근 {args.days}일 신호 {n}건 · {len(days)}거래일 · 하루 평균 {per_day:.1f}건"
        f" · 종목 {len(by_ticker)}개 · DART 호출 {calls + 1}회 · 020 {rate_limited}회",
        "",
        "## 등급 분포",
        "",
        "| 🔴 red | 🟡 amber | none | unknown | error |",
        "|---|---|---|---|---|",
        f"| {pct('red')} | {pct('amber')} | {pct('none')} | {pct('unknown')} | {pct('error')} |",
        "",
        "## 전략별",
        "",
        "| 전략 | 건수 | 🔴 | 🟡 | none | unknown | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for strat, cnt in by_strategy.items():
        tot = sum(cnt.values())
        lines.append(
            f"| {STRATEGY_LABELS.get(strat, strat)} | {tot} | {cnt['red']} | {cnt['amber']}"
            f" | {cnt['none']} | {cnt['unknown']} | {cnt['error']} |"
        )
    lines += ["", "## 걸린 규칙 (플래그 수)", "", "| 규칙 | 건수 |", "|---|---|"]
    lines += [f"| {r} | {k} |" for r, k in rules.most_common()]
    lines += [
        "",
        f"## 🔴 전 건 — 원문 링크로 손검증 ({len(reds)}건)",
        "",
        "| 신호일 | 종목 | 전략 | 규칙 | 공시 | 원문 |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {s.d} | {s.name} [{s.ticker}] | {s.strategy} | {rule} | {nm} | [원문]({link}) |"
        for s, rule, nm, link in reds
    ]
    lines += [
        "",
        f"## 🟡 표본 (앞 30건 / {len(ambers)}건)",
        "",
        "| 신호일 | 종목 | 규칙 | 공시 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {s.d} | {s.name} [{s.ticker}] | {rule} | {nm} |" for s, rule, nm in ambers[:30]]
    unknown_names = sorted({(s.ticker, s.name) for s in signals if s.ticker not in codes})
    if unknown_names:
        lines += [
            "",
            f"## DART 미등록 ({len(unknown_names)}종목)",
            "",
            ", ".join(f"{n_} [{t}]" for t, n_ in unknown_names),
        ]

    out = config.PROJECT_ROOT / args.out
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:10]))
    print(f"\n[out] {out.relative_to(config.PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
