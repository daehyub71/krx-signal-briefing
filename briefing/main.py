"""CLI 진입점.

부수효과(시간·네트워크·DB)를 아는 몇 안 되는 곳이다.
**기준일을 여기서 정해 상태에 주입한다** — 노드가 "오늘"을 직접 알면 재현이 성립하지 않는다.

진입 경로(SPEC F0)는 여기서 구분하지 않는다. 그래프는 자기가 dispatch로 깨어났는지
예비 cron으로 깨어났는지 모른다 — 예비 cron은 `--if-not-briefed`로 no-op만 얹는다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from briefing import config, store
from briefing.graph import build_graph
from briefing.nodes import BriefingRunError
from briefing.state import initial_state


def parse_date(value: str | None) -> date:
    """`--date YYYYMMDD`를 날짜로 바꾼다. 없으면 오늘."""
    return datetime.strptime(value, "%Y%m%d").date() if value else date.today()


def build_parser() -> argparse.ArgumentParser:
    """인자 파서를 만든다."""
    p = argparse.ArgumentParser(prog="briefing", description="신호 검증 브리핑 배치")
    p.add_argument("--date", help="기준일 YYYYMMDD (기본: 오늘)")
    p.add_argument("--dry-run", action="store_true", help="저장·발송하지 않고 결과만 출력한다")
    p.add_argument(
        "--force", action="store_true",
        help="기존 브리핑·요약이 있어도 다시 만든다 (DART·LLM 재호출)",
    )
    p.add_argument(
        "--if-not-briefed", action="store_true",
        help="예비 cron용 — 오늘 ksb_runs가 이미 있으면 아무것도 하지 않는다",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """배치를 실행한다.

    Args:
        argv: 명령행 인자. None이면 `sys.argv`를 쓴다.

    Returns:
        종료 코드. 0은 성공(no-op 포함), 1은 실패 — 워크플로가 실패해야 한다 (N5).
    """
    args = build_parser().parse_args(argv)
    config.load_env()
    run_date = parse_date(args.date)

    try:
        if args.if_not_briefed and store.briefed_today(store.conn(), run_date):
            print(f"[briefing] {run_date} 브리핑이 이미 있다 — 예비 cron no-op")
            return 0

        flags = " · ".join(f for f, on in (("dry-run", args.dry_run), ("force", args.force)) if on)
        print(f"[briefing] 기준일 {run_date}{' · ' + flags if flags else ''}")

        state = initial_state(run_date, dry_run=args.dry_run, force=args.force)
        final = build_graph().invoke(state)
    except BriefingRunError as exc:
        print(f"[briefing] 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()

    print(
        f"[briefing] status={final['status']} "
        f"signals={len(final.get('signals', []))} briefings={len(final.get('briefings', []))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
