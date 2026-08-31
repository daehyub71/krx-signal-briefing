# krx-signal-briefing

> 🇰🇷 한국어: [README_KO.md](README_KO.md)

**A second morning e-mail that checks whether a chart signal is backed by anything.**

[krx-signal-alerts](https://github.com/daehyub71/krx-signal-alerts) screens every KRX stock against five
technical strategies and mails the hits at 08:20 KST. That mail only says *"the chart conditions are met"*.
It cannot tell a clean breakout from one sitting on top of a convertible bond issued last week.

This project answers the next question — **is there evidence, and does it agree with the chart?** — by
pulling three independent streams for each signalled stock and reconciling them:

```
chart signal (upstream)   "MTF alignment" · "VCP contraction"
      │
      ├─ 1  DART filings   what happened   — CB ₩12.0bn, 18.63% potential dilution, refix clause
      ├─ 2  Naver news     why it happened — "the entire amount goes to a second plant"
      └─ 3  Investor flows who bought/sold — 30 days of institutional vs. foreign net buying
      │
      ▼
  corroborates / contradicts / unrelated   + a written case + a rule-based score
```

**The verdict and the score are computed in code, not by the model.** `verdict.judge()` is a pure function;
Claude only *explains* the verdict it is handed. Ask a model for a number and it will invent one — that
happened here on 2026-08-30, and the fix was to stop asking.

> **Status** — M0–M3 and M6 complete, M4 (automation) at 85%. 554 tests, ruff and mypy strict clean,
> running end-to-end in GitHub Actions: gate → 44 signals → 34 written analyses → Vercel page → mail.
> Remaining: five consecutive trading days of observation.

## What one stock's block looks like

Real output, 2026-08-26, plain-text part of the mail:

```
엔투텍 [227950]
  ─────────────────────────────────────────────
  🔴 공시 8건 · 위험 유형 4건
     · 08/25 [정정] [기재정정]주요사항보고서(전환사채권발행결정) ←🔴
       https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260825000352
     · 08/21 주요사항보고서(전환사채권발행결정) ←🔴
       https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000442
     · 08/14 반기보고서 (2026.06)
       https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814002772
  📊 공시 이상 점수 25/100 · watch
  💰 시총 476억 · 5일 거래대금 17억
  📰 뉴스 4건 — HTML 본문과 전문 페이지에 있습니다
  💬 8/21 전환사채권발행결정 2건과 8/25 그 기재정정 2건이 모두 위험 유형으로 걸려 🔴4건(-24)이다.
     본문상 120억원은 타법인증권취득자금 전액이고 잠재 물량 18.63%, 30억원은 운영자금 전액이며
     5.41%로 합산 24.04%, 둘 다 전환가액 1,519원에 시가하락 시 조정 조항(하한 1,064원)이 붙어 있다. …

이 메일은 공시 사실을 나열합니다. 매매 판단의 근거가 아닙니다.
```

A VCP breakout, and underneath it four convertible-bond filings diluting by a quarter of the float with a
refix clause attached. **Verdict: contradicts, 26/100.** The `18.63%` and `1,519원` are read out of the
filing *body* — neither number appears in any filing title.

Facts only, every filing linked to its DART original, no buy/sell language. A stock with nothing flagged
says *"no risk type confirmed among filings in the last 30 days"* — never *"no risk"*.

## How it decides

| Layer | What it contributes |
|---|---|
| **Filings** (F5, F15, F16) | A transparent keyword rule table grades filings 🔴/🟡. Routine ones (semi-annual reports, IR notices) are folded away — they were 65% of the noise. Flagged filings get their **body** parsed for overhang %, use of funds, coupon and refix terms. |
| **News** (F11 v2) | Company name as the query, relevance order, and a title filter that rejects a match preceded by a Hangul syllable — otherwise `아이텍` matches inside `위세아이텍`. Title relevance went 64% → 100% in real collection. |
| **Flows** (F17) | 30 days of institutional / foreign / retail net buying, read with one SQL query from the upstream database. No extra API, no extra key. |
| **Verdict** (F18) | `verdict.judge()` — pure. Weights for flags, overhang cap, refix, anomaly, flow direction. The output carries its own **blind spots**: earnings, valuation, sector, the broad market, and price action after the filing. |
| **Written case** (F19) | One batched Claude Opus 5 call per day, ≤2,000 characters per stock, validated in code against forbidden wording, the tickers in the input, and the risk counts we counted for it. |

## Architecture

![System overview](docs/arch-overview.png)

- **Read-only consumer** of the upstream tables (`ksa_signals`, `ksa_runs`, `ksc_*`). Writes only to its own
  `ksb_*` tables, which carry **no RLS policy at all** — service_role only.
- **Two third-party MCP servers** (`npx`, stdio, pinned versions) sit between the batch and the external APIs:
  [korean-dart-mcp](https://github.com/chrisryugj/korean-dart-mcp) and
  [naver-search-mcp](https://github.com/isnow890/naver-search-mcp). They are **data sources, not agents** —
  the batch calls their tools in a fixed order from Python and the LLM never holds a tool. If korean-dart-mcp
  times out the batch falls back to OpenDART REST directly; every other layer is optional and its absence is
  marked in the mail.
- **Triggered by `repository_dispatch`** from the last step of the upstream `alert.yml` — measured at 20
  seconds from HTTP 204 to workflow start. A backup cron (09:05 KST) covers a missed dispatch and is a no-op
  if the day already ran.
- **The mail is kept short; the full text is a Vercel page** it links to. That page keeps Vercel's SSO
  protection on, so it stays owner-only, and states on every screen that it is a test artifact and not advice.

![LangGraph graph](docs/graph.png)

Three layers, same rules as the upstream project. The graph layer (`state` · `nodes` · `graph`) is the only
place that knows LangGraph and every node stays under 20 lines. The domain layer (`flags` · `routine` ·
`verdict` · `analysis` · `render` · `page` · `corp`) is pure functions and the TDD target. The I/O layer
(`enrich` · `dart` · `dart_mcp` · `news_mcp` · `mcpc` · `llm` · `store` · `notify` · `deploy` · `config`) is
the only place with side effects, and its nodes never raise — an exception there would skip `record_run` and
erase the day's own failure record.

![Module dependencies](docs/modules.png)

## Stack

Python 3.11 + Node 20.19 · LangGraph · **MCP Python SDK** (stdio client) · korean-dart-mcp / naver-search-mcp ·
Anthropic SDK (`claude-opus-5`, one batched streaming call per day) · OpenDART REST as fallback ·
Supabase (psycopg + supabase-py) · Gmail SMTP · Vercel Deployments API · GitHub Actions · pytest / ruff / mypy (strict)

## Setup

```bash
cd krx-signal-briefing
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env           # DART, Anthropic, Naver, Supabase, Gmail, Vercel
node --version                 # 20.19+ — the MCP servers run via npx
python scripts/apply_schema.py # create ksb_* tables (idempotent)
```

## Run

```bash
python -m briefing.main --dry-run            # no persist, no mail
python -m briefing.main --date 20260828      # reproduce a past day
python -m briefing.main --force              # rebuild even if today's briefing exists
python -m briefing.main --if-not-briefed     # backup-cron mode: no-op if already run today
python scripts/dryrun.py --days 60           # grade past signals, no mail/LLM
python scripts/export_graph.py               # regenerate docs/GRAPH.md after changing the graph
```

## Verify

```bash
ruff check . && mypy && pytest -q
```

## Docs

| File | Content |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | Requirements (F/N/R IDs), decisions D1–D24, data model, wording rules |
| [docs/PLAN.md](docs/PLAN.md) | Architecture, graph design, milestones, test strategy |
| [docs/DESIGN.md](docs/DESIGN.md) | Mail and page layout, agreed with the recipient before it was built |
| [docs/TASKS.md](docs/TASKS.md) | Progress dashboard, task checklist, troubleshooting log |
| [docs/GRAPH.md](docs/GRAPH.md) | Auto-generated mermaid of the compiled graph |
| [docs/TOKENS.md](docs/TOKENS.md) | Token issue and rotation procedures |

## Boundaries

- **Not investment advice.** It reports what was filed, published and traded, and whether those agree with the
  chart. It never recommends, rates, or predicts. Forbidden wording is enforced in the renderer, in the LLM
  prompt, and in code that validates the LLM's output — an analysis that trips it is dropped, not softened.
- **Single recipient.** Distributing interpreted signals to others would fall under Korean investment-advisory
  regulation, so `RECIPIENTS` stays at one person and the full-text page stays behind SSO.
- The score is deliberately partial and says so: it does not look at earnings, valuation, the sector, the
  broad market, or what the price did after the filing.
- Only filings within a 30-day window are seen.

## License

MIT
