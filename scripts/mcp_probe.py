"""MCP 서버 기동·도구 확인 — 실측용 (M1b 완료 기준 · N14 계약 확인).

    python scripts/mcp_probe.py                 # 3종 기동 시간 + 도구 목록
    python scripts/mcp_probe.py --tools         # 도구 이름까지 전부
    python scripts/mcp_probe.py --sample 00126380   # 삼성전자로 도구 호출 표본까지

CI에서도 이걸 돌려 **기동 시간을 기록**한다. 키가 없는 서버는 `McpStartError`로 건너뛴다 —
실패가 아니라 "그 층은 오늘 없다"는 뜻이다 (D15).
**키는 절대 출력하지 않는다** (N7).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from briefing import config, mcpc  # noqa: E402

SAMPLE_CALLS: dict[str, list[tuple[str, Callable[[str], dict[str, Any]]]]] = {
    "dart": [
        ("search_disclosures", lambda corp: {"corp": corp, "days": 30, "all_pages": True}),
        ("disclosure_anomaly", lambda corp: {"corp": corp}),
        ("insider_signal", lambda corp: {"corp": corp}),
    ],
    "stock": [
        ("get_corp_code", lambda corp: {"stock_code": "005930"}),
        (
            "get_stock_trade_info",
            lambda corp: {
                "basDdList": [(date.today() - timedelta(days=1)).strftime("%Y%m%d")],
                "market": "KOSPI",
                "codeList": ["005930"],
            },
        ),
    ],
    "naver": [("search_news", lambda corp: {"query": "삼성전자", "display": 3, "sort": "date"})],
}


def probe(name: str, *, show_tools: bool, sample_corp: str | None) -> bool:
    """서버 하나를 띄워 보고 결과를 출력한다. 기동에 성공하면 True."""
    spec = mcpc.SERVERS[name]
    t0 = time.time()
    try:
        server = mcpc.get(name)
    except mcpc.McpStartError as exc:
        print(f"⏭  {name:6} {spec.package}@{spec.version} — 건너뜀: {exc}")
        return False
    took, pkg = time.time() - t0, f"{spec.package}@{spec.version}"
    print(f"✅ {name:6} {pkg} · 기동 {took:.1f}초 · 도구 {len(server.tools)}개")
    if show_tools:
        print("   도구: " + ", ".join(server.tools))
    if sample_corp is None:
        return True
    for tool, make_args in SAMPLE_CALLS.get(name, []):
        t1 = time.time()
        try:
            body = server.call(tool, make_args(sample_corp), timeout=60)
            print(f"   ▶ {tool:22} {time.time() - t1:5.1f}초 · {len(body):,}자")
        except mcpc.McpError as exc:
            print(f"   ▶ {tool:22} {time.time() - t1:5.1f}초 · 실패: {str(exc)[:80]}")
    return True


def main(argv: list[str] | None = None) -> int:
    """3종을 순서대로 띄워 본다."""
    p = argparse.ArgumentParser(prog="mcp_probe")
    p.add_argument("--tools", action="store_true", help="도구 이름을 전부 출력")
    p.add_argument("--sample", metavar="CORP_CODE", help="도구 호출 표본까지 (예: 00126380)")
    p.add_argument("--require", nargs="*", default=["dart"], help="반드시 떠야 하는 서버")
    args = p.parse_args(argv)
    config.load_env()

    started: set[str] = set()
    t0 = time.time()
    try:
        for name in mcpc.SERVERS:
            if probe(name, show_tools=args.tools, sample_corp=args.sample):
                started.add(name)
    finally:
        mcpc.close_all()
    print(f"\n총 {time.time() - t0:.1f}초 · 기동 {len(started)}/{len(mcpc.SERVERS)}종")

    missing = [n for n in args.require if n not in started]
    if missing:
        print(f"필수 서버 미기동: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
