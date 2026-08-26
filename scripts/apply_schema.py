"""`supabase/schema.sql`을 적용한다 (멱등).

supabase-py는 DDL을 지원하지 않아 psycopg로 직접 붙는다.

    python scripts/apply_schema.py            # 적용
    python scripts/apply_schema.py --check    # 적용하지 않고 현재 상태만 본다
    python scripts/apply_schema.py --verify   # 적용 후 anon 역할로 쓰기가 막히는지 확인 (롤백)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402

from briefing import config  # noqa: E402

SCHEMA = config.PROJECT_ROOT / "supabase" / "schema.sql"
OWNED = ("ksb_briefings", "ksb_runs")

INSPECT = """
select c.relname,
       c.relrowsecurity,
       (select count(*) from pg_policies p
         where p.schemaname = 'public' and p.tablename = c.relname),
       (select count(*) from pg_index i where i.indrelid = c.oid)
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relname = any(%s)
 order by c.relname
"""


def connect() -> psycopg.Connection[tuple[object, ...]]:
    """DB에 붙는다. URL은 트랜잭션 풀러라 `prepare_threshold=None`."""
    return psycopg.connect(config.require("SUPABASE_DATABASE_URL"), prepare_threshold=None)


def report(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """소유 테이블의 현재 상태를 출력한다."""
    rows = conn.execute(INSPECT, (list(OWNED),)).fetchall()
    if not rows:
        print("  (ksb_* 테이블이 아직 없다)")
        return
    for name, rls, policies, indexes in rows:
        print(f"  {name:14} RLS={'on' if rls else 'OFF'}  정책 {policies}개  인덱스 {indexes}개")


def verify_anon(conn: psycopg.Connection[tuple[object, ...]]) -> bool:
    """anon 역할로 읽기는 되고 쓰기는 막히는지 확인한다. 전부 트랜잭션 안에서 롤백한다.

    Returns:
        읽기 성공 · 쓰기 거부면 True.
    """
    ok = True
    # 바깥 트랜잭션은 마지막에 통째로 롤백한다. 안쪽은 세이브포인트 — 거부돼도 바깥이 살아 있다.
    conn.execute("set local role anon")
    n = conn.execute("select count(*) from ksb_runs").fetchone()
    print(f"  anon SELECT ksb_runs → {n[0] if n else '?'}행 (허용)")
    try:
        with conn.transaction():
            conn.execute("insert into ksb_runs (status) values ('ok')")
        print("  anon INSERT ksb_runs → ❌ 통과했다 (RLS가 막지 못함)")
        ok = False
    except psycopg.errors.InsufficientPrivilege as exc:
        print(f"  anon INSERT ksb_runs → 차단 ✅ ({exc.sqlstate})")
    conn.rollback()
    return ok


def main(argv: list[str] | None = None) -> int:
    """스키마를 적용하고 결과를 보고한다."""
    parser = argparse.ArgumentParser(prog="apply_schema")
    parser.add_argument("--check", action="store_true", help="적용하지 않고 상태만 본다")
    parser.add_argument("--verify", action="store_true", help="anon 쓰기 차단 확인 (롤백)")
    args = parser.parse_args(argv)

    config.load_env()
    with connect() as conn:
        print("[적용 전]")
        report(conn)
        if args.check:
            return 0

        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
        print("\n[적용 후]")
        report(conn)

        if args.verify:
            print("\n[anon 권한 확인]")
            if not verify_anon(conn):
                return 1

    print("\n스키마 적용 완료. ksa_*·ksc_* 테이블은 건드리지 않았다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
