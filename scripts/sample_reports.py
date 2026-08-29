"""실제 `report_nm` 표본을 모은다 (M1). 규칙표(SPEC F5)를 확정하는 근거다.

    python scripts/sample_reports.py                 # 최근 90일(≈60거래일) 신호 종목 전부
    python scripts/sample_reports.py --limit 20      # 빠른 확인
    python scripts/sample_reports.py --window 120    # 종목당 공시 조회 창(일)

하는 일 세 가지:
  ① `ksa_signals`에서 최근 신호 종목(억제 제외)을 뽑는다
  ② `corpCode.xml`을 받아 실파일 구조를 표본(`corpcode_sample.xml`)과 대조한다 — TASKS 미해소 이슈 ⑥
  ③ 종목마다 `list.json` 1회로 공시 제목을 모아 `tests/fixtures/report_names.txt`(빈도순)와
     `tests/fixtures/list_sample.json`(원문 몇 건)을 쓴다

발송·저장·LLM은 없다. DART 호출은 종목 수 + 1회.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from briefing import config, corp, dart, store  # noqa: E402
from briefing.models import Disclosure  # noqa: E402

FIXTURES = config.PROJECT_ROOT / "tests" / "fixtures"
OUT_NAMES = FIXTURES / "report_names.txt"
OUT_JSON = FIXTURES / "list_sample.json"


def check_corp_codes(codes: dict[str, str], raw_count: int) -> None:
    """실파일이 표본의 가정(비상장 공백·문자 티커·중복)과 맞는지 보고한다."""
    lettered = [t for t in codes if not t.isdigit()]
    print(
        f"[corp] zip {raw_count:,} bytes → 상장사 {len(codes):,}개"
        f" · 문자 섞인 티커 {len(lettered)}개 (예: {lettered[:4]})"
    )
    known = (("삼성전자", "005930"), ("가비아", "079940"), ("코스맥스엔비티", "222040"))
    for name, ticker in known:
        print(f"       {name} {ticker} → {codes.get(ticker, '없음')}")


def collect(
    pairs: list[tuple[str, str]], codes: dict[str, str], bgn: date, end: date, pause: float
) -> tuple[collections.Counter[str], list[Disclosure], list[tuple[str, str]], int]:
    """종목별 공시 제목을 모은다.

    Returns:
        (제목 빈도, 원문 표본, DART 미등록 종목, 호출 수)
    """
    names: collections.Counter[str] = collections.Counter()
    sample: list[Disclosure] = []
    unknown: list[tuple[str, str]] = []
    calls = 0
    for i, (ticker, name) in enumerate(pairs, 1):
        code = codes.get(ticker)
        if code is None:
            unknown.append((ticker, name))
            continue
        items = dart.fetch_disclosures(code, bgn, end)
        calls += 1
        names.update(x.report_nm for x in items)
        if len(sample) < 12:
            sample.extend(items[:2])
        print(f"  {i:3}/{len(pairs)} {name} [{ticker}] {len(items)}건")
        time.sleep(pause)
    return names, sample, unknown, calls


def main(argv: list[str] | None = None) -> int:
    """표본을 모아 파일로 쓴다."""
    p = argparse.ArgumentParser(prog="sample_reports")
    p.add_argument("--days", type=int, default=90, help="신호 조회 범위(달력일). 90 ≈ 60거래일")
    p.add_argument("--window", type=int, default=120, help="종목당 공시 조회 창(일)")
    p.add_argument("--limit", type=int, default=0, help="종목 수 상한 (0=전부)")
    p.add_argument("--pause", type=float, default=0.1, help="호출 간격(초)")
    args = p.parse_args(argv)
    config.load_env()

    today = date.today()
    c = store.conn()
    try:
        pairs = store.fetch_signal_tickers_since(c, today - timedelta(days=args.days))
    finally:
        store.close()
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"[signals] 최근 {args.days}일 신호 종목 {len(pairs)}개")

    try:
        raw = dart.fetch_corp_codes()
        codes = corp.parse_corp_codes(raw)
    except (dart.DartError, corp.CorpCodeError) as exc:
        print(f"[corp] 실패: {exc}", file=sys.stderr)
        return 1
    check_corp_codes(codes, len(raw))

    bgn, end = today - timedelta(days=args.window), today
    try:
        names, sample, unknown, calls = collect(pairs, codes, bgn, end, args.pause)
    except dart.DartError as exc:
        print(f"[dart] 중단: {exc}", file=sys.stderr)
        return 1

    header = (
        f"# 실제 report_nm 표본 — {today} · 신호 종목 {len(pairs)}개"
        f" · 창 {args.window}일 · 호출 {calls}회\n"
        "# 형식: 빈도<TAB>제목  (빈도순). 규칙표(SPEC F5) 확정 근거.\n"
    )
    OUT_NAMES.write_text(
        header + "".join(f"{n}\t{nm}\n" for nm, n in names.most_common()), encoding="utf-8"
    )
    OUT_JSON.write_text(
        json.dumps([x.to_json() for x in sample], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rel = OUT_NAMES.relative_to(config.PROJECT_ROOT)
    print(f"\n[out] {rel} — 제목 {len(names)}종, 공시 {sum(names.values())}건")
    print(f"[out] {OUT_JSON.relative_to(config.PROJECT_ROOT)} — 원문 {len(sample)}건")
    print(f"[dart] 호출 {calls + 1}회 (corpCode 1 + list {calls})")
    if unknown:
        print(f"[unknown] DART 미등록 {len(unknown)}개: {unknown[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
