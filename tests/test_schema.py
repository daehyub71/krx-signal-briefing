"""`supabase/schema.sql`이 브리핑 내용을 다시 공개하지 않는지 지킨다 (2026-08-31 보안 점검).

`ksb_briefings`에 anon SELECT 정책이 걸려 있어 **공개된 anon 키로 15행이 통째로 읽혔다** —
티커·종목명·공시 목록·등급·판정·근거 서술까지. 그 anon 키는 상위 `krx-stock-charts`
웹 번들에 실려 있다 (SPEC R6). 전문 페이지를 Vercel SSO로 잠근 이유(R7 v3.1)가
이 구멍으로 무력화됐다 — 페이지를 막아도 DB에서 꺼낼 수 있으면 소용이 없다.

`create policy … to anon`을 다시 넣으면 이 테스트가 잡는다.
"""

from __future__ import annotations

import re
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "supabase" / "schema.sql"

# `create policy <이름> on <표> for <명령> to <역할…>` — 줄바꿈이 섞여도 잡는다.
_POLICY = re.compile(r"create\s+policy\s+(\S+)\s+on\s+(\S+).*?\sto\s+([^\n]+)", re.I | re.S)


def _sql() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def test_schema_grants_no_policy_to_anon() -> None:
    """anon·authenticated에게 어떤 권한도 주지 않는다. service_role만 RLS를 우회한다."""
    granted = [
        (name, table, roles.strip())
        for name, table, roles in _POLICY.findall(_sql())
        if "anon" in roles or "authenticated" in roles
    ]
    assert not granted, f"anon/authenticated에 정책이 열렸다: {granted}"


def test_ksb_tables_keep_rls_enabled() -> None:
    """RLS 자체는 켜 둔다 — 정책이 없어도 RLS가 꺼져 있으면 anon이 전부 읽는다."""
    sql = _sql()
    for table in ("ksb_briefings", "ksb_runs"):
        assert re.search(
            rf"alter\s+table\s+{table}\s+enable\s+row\s+level\s+security", sql, re.I
        ), f"{table}에 RLS 활성화 구문이 없다"
