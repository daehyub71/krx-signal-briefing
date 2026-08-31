# GRAPH.md — 그래프 구조

> **이 파일은 `scripts/export_graph.py`가 생성한다. 직접 고치지 않는다.**
> 그래프를 바꿨으면 스크립트를 다시 돌려 커밋한다 (SPEC N12).
>
> 설계 의도와 각 노드가 하는 일은 `PLAN.md` §1-1, 설계도는 `graph.png`를 본다.
> `fetch_one`은 종목마다 `Send()`로 띄우는 fan-out 노드다 — 그림에는 하나로 보인다.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	gate(gate)
	wait(wait)
	load_signals(load_signals)
	load_corps(load_corps)
	load_market(load_market)
	fetch_one(fetch_one)
	analyze(analyze)
	publish(publish)
	render(render)
	persist(persist)
	send_email(send_email)
	record_run(record_run)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> gate;
	analyze --> publish;
	fetch_one --> analyze;
	gate -. &nbsp;ready&nbsp; .-> load_signals;
	gate -. &nbsp;timeout&nbsp; .-> record_run;
	gate -. &nbsp;stale&nbsp; .-> render;
	gate -. &nbsp;missing&nbsp; .-> wait;
	load_corps --> load_market;
	load_market -.-> analyze;
	load_market -.-> fetch_one;
	load_signals --> load_corps;
	persist --> send_email;
	publish --> render;
	record_run --> finalize;
	render --> persist;
	send_email --> record_run;
	wait --> gate;
	finalize --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
