# krx-signal-briefing

> 🇰🇷 한국어: [README_KO.md](README_KO.md)

**A second morning e-mail that attaches recent DART filings to each stock signal.**

[krx-signal-alerts](https://github.com/daehyub71/krx-signal-alerts) screens every KRX stock against five
technical strategies and mails the hits at 08:20 KST. That mail only says *"the chart conditions are met"*.
It cannot tell a clean breakout from one that sits on top of a convertible-bond issue announced last week.

This project fills that gap. When the upstream workflow finishes, it wakes up, reads the same signals,
pulls each company's filings from the last 30 days through **korean-dart-mcp** (OpenDART), grades them with a
transparent keyword rule table (🔴 / 🟡), adds side signals (disclosure-anomaly score, insider trading clusters,
market cap read from the upstream database), looks up news through **naver-search-mcp** only for stocks nothing was flagged on,
asks **Claude Opus 5** for a one-line factual summary, and sends a second mail that lines up 1:1 with the first.

The MCP servers are **data sources, not agents**: the batch calls their tools in a fixed order from Python
(MCP SDK stdio client); the LLM never holds a tool. That keeps the run deterministic and the cost at one
batched Claude call per day.

> **Status: M0 · M1 · M1b complete (32/70)** — 2026-08-29. The rule table was built from 3,000 real filings and then checked against 12 DART originals (11/12 correct); a dry run over 165 signals gives 🔴 8% · 🟡 8% · none 84%. Next: news (M1c), then rendering and delivery. Not yet deployed.

## What the second mail looks like

```
가비아 [079940] 46,000원 +1.32%
  ✓ 월봉 종가 > MA20 : …            ← the five condition lines from the first mail, verbatim
  ─────────────────────────────────────────────
  🔴 공시  최근 30일 4건 · 위험 유형 2건
           · 08/22 전환사채권발행결정          [원문]  ← 🔴
           · 08/11 최대주주변경                [원문]  ← 🔴
           · 08/05 분기보고서                  [원문]
  💬 08/22 CB 발행 결정, 08/11 최대주주 변경 — 최근 30일 위험 유형 2건
```

Facts only, every filing linked to its DART original, no buy/sell language. A stock with nothing flagged
says *"no risk type confirmed among filings in the last 30 days"* — never *"no risk"*.

## Architecture

![System overview](docs/arch-overview.png)

- **Read-only consumer** of the upstream tables (`ksa_signals`, `ksa_runs`). Writes only to its own `ksb_*` tables in the same Supabase project.
- **Two third-party MCP servers** (`npx`, stdio, pinned versions) sit between the batch and the external APIs: [korean-dart-mcp](https://github.com/chrisryugj/korean-dart-mcp) (filings, anomaly score, insider clusters) and [naver-search-mcp](https://github.com/isnow890/naver-search-mcp) (news). If korean-dart-mcp is down the batch falls back to calling OpenDART REST directly; the other layers are simply skipped and marked in the mail.
- **Market cap comes from the upstream database, not another API.** `krx-stock-charts` already talks to KRX, so it stores 시가총액 and 상장주식수 on its daily run and this batch reads them together with five days of turnover in a single query — no extra key, no extra call. (An earlier draft used [korea-stock-mcp](https://github.com/jjlabsio/korea-stock-mcp), which would have needed a KRX OPEN API key.)
- **Triggered by `repository_dispatch`** from the last step of the upstream `alert.yml`, so it starts within seconds of the signal mail. A backup cron (09:05 KST) covers a missed dispatch and is a no-op if the day already ran.
- **LangGraph** state graph with a DB gate (retry 1 min × 10), per-ticker `Send()` fan-out for DART lookups, and an isolated `summarize` node — if the LLM fails, the mail still goes out with a warning line.

![LangGraph graph](docs/graph.png)

Three layers, same rules as the upstream project: the graph layer is the only place that knows LangGraph;
the domain layer (`corp` · `flags` · `render` · `summary`) is pure functions and the TDD target; the I/O layer
(`dart` · `llm` · `store` · `notify`) is the only place with side effects.

![Module dependencies](docs/modules.png)

## Stack

Python 3.11 + Node 20.19 · LangGraph · **MCP Python SDK** (stdio client) · korean-dart-mcp / naver-search-mcp · Anthropic SDK (`claude-opus-5`, one batched call per day) ·
OpenDART REST as fallback · Supabase (psycopg + supabase-py) · Gmail SMTP · GitHub Actions · pytest / ruff / mypy (strict)

## Setup

```bash
cd krx-signal-briefing
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env           # DART_API_KEY, ANTHROPIC_API_KEY, Naver NCP keys, Supabase, Gmail
node --version                 # 20.19+ — the MCP servers run via npx
python scripts/apply_schema.py --verify   # create ksb_* tables, confirm anon cannot write
```

## Run

```bash
python -m briefing.main --dry-run            # no persist, no mail
python -m briefing.main --date 20260825      # reproduce a past day
python -m briefing.main --force              # rebuild even if today's briefing exists
python -m briefing.main --if-not-briefed     # backup-cron mode: no-op if already run today
python scripts/sample_reports.py             # collect real DART report titles → tests/fixtures/report_names.txt
python scripts/dryrun.py                     # grade past signals, no mail/LLM → docs/dryrun_m1.md
```

## Verify

```bash
ruff check . && mypy && pytest -q
python scripts/export_graph.py               # regenerate docs/GRAPH.md after changing the graph
```

## Docs

| File | Content |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Requirements (F/N/R IDs), decisions D1–D11, data model, wording rules |
| [docs/PLAN.md](docs/PLAN.md) | Architecture, graph design, milestones M0–M5, test strategy |
| [docs/TASKS.md](docs/TASKS.md) | Progress dashboard, task checklist, troubleshooting log |
| [docs/GRAPH.md](docs/GRAPH.md) | Auto-generated mermaid of the compiled graph |
| [docs/dryrun_m1.md](docs/dryrun_m1.md) | Dry-run report — grade distribution and every 🔴 with its DART link |

## Boundaries

- **Not investment advice.** The mail lists filings; it never recommends, rates, or predicts.
- **Single recipient.** Distributing interpreted signals to others would fall under Korean investment-advisory regulation.
- Only filings within the 30-day window are seen. Anything outside it — or inside a report body — is not.

## License

MIT
