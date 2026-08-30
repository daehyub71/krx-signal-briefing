# TASKS.md — krx-signal-briefing

> 기준: `SPEC.md` v1.1 · `PLAN.md` v1.0 (2026-08-26)
> 저장소: `daehyub71/krx-signal-briefing` (public) · 트리거: 상위 `alert.yml` → `repository_dispatch` · 예비 cron 평일 09:05 KST
> 체크할 때마다 아래 대시보드를 함께 갱신한다. 마일스톤을 닫을 때는 **ruff · mypy strict · pytest 전부 통과**가 전제다.

---

## 진도율 대시보드

| 마일스톤 | 진도 | % | 태스크 | 상태 |
|----------|------|---|--------|------|
| M0 뼈대 + 걷는 해골 | `██████████` | 100% | 12/12 | ✅ 2026-08-26 |
| M1 DART 계층 ★ TDD | `██████████` | 100% | 10/10 | ✅ 2026-08-29 |
| **M1b MCP 계층** (v2.0) | `██████████` | 100% | 10/10 | ✅ 2026-08-29 |
| **M1c 뉴스** (v2.0) | `██████████` | 100% | 5/5 | ✅ 2026-08-29 |
| M2 본문·저장·발송 | `██████████` | 100% | 10/10 | ✅ 2026-08-29 |
| M3 Claude 요약 | `██████████` | 100% | 8/8 | ✅ 2026-08-30 |
| M4 자동화·배포 | `░░░░░░░░░░` | 0% | 0/11 | 🔜 |
| M5 마무리 | `░░░░░░░░░░` | 0% | 0/5 | 🔜 |
| **M6 신호 검증 (v3.0)** | `█░░░░░░░░░` | 12% | 2/17 | 🔄 |
| **전체** | `██████░░░░` | **65%** | **57/88** | 🔄 M6 |

범례: 🔜 대기 · 🔄 진행중 · ✅완료일

**사용자 준비물 (블로커)**

| 시점 | 항목 | 상태 |
|------|------|------|
| M0 전 | OpenDART 인증키 (opendart.fss.or.kr, 무료·즉시) → `.env` `DART_API_KEY` | ✅ 2026-08-26 연결 확인 |
| M0 전 | 깃허브 리포 `krx-signal-briefing` 생성 (public) | ✅ 2026-08-26 첫 푸시 |
| M3 전 | Anthropic API 키 → `.env` `ANTHROPIC_API_KEY` | ✅ 2026-08-26 연결 확인 |
| **M1b 전** | **D12·D13·D15 확정** (SPEC §2-3). D14는 ✅ 포함 확정(2026-08-29) | ⏳ |
| ~~M1b/M4~~ | ~~KRX OPEN API 키~~ — **불필요해짐** (D14 v2: 상위가 기존 `KRX_ID`/`KRX_PW`로 수집) | ✅ 해소 |
| **M1c 전** | **네이버 검색 API 키** — ① NCP API HUB `NCP_APIGW_API_KEY_ID`+`NCP_APIGW_API_KEY`(권장) **또는** ② 개발자센터 `NAVER_CLIENT_ID`+`NAVER_CLIENT_SECRET`(즉시 발급·카드 불필요). **둘 중 한 쌍만** 채우면 된다 | ⏳ |
| M4 | fine-grained PAT (대상 `krx-signal-briefing` 1개 · Contents write · 1년) → 상위 리포 Secrets `BRIEFING_DISPATCH_TOKEN` | ⏳ |
| M4 | 이 리포 Secrets 8종 등록 | ⏳ |

---

## M0 — 뼈대 + 걷는 해골

> **그래프를 먼저 세우고 노드를 나중에 채운다** (상위 PLAN에서 배운 순서). 노드를 다 만든 뒤 조립하면 reducer·조건부 엣지·`Send` 합류가 한꺼번에 터진다.

- [x] venv 생성(python3.11) · `requirements.txt`(langgraph · anthropic · supabase · psycopg[binary] · certifi) · `requirements-dev.txt`(ruff · mypy · pytest) — **이 디렉토리에서** pip · 자격증명 4종 연결 확인(DART · Anthropic · Supabase · Gmail, 2026-08-26)
- [x] `pyproject.toml` — ruff 설정 + mypy strict · `.gitignore`(`.env` · `venv/` · `__pycache__` · `.DS_Store`) · `.env.example`(키 이름만)
- [x] `CLAUDE.md` — 프로젝트 규칙(3층 분리 · 노드 20줄 · `ksa_*`/`ksc_*` 읽기만 · 문구 규칙 N1 · 조심할 것)
- [x] `briefing/config.py`(기존 환경변수 덮어쓰지 않는 로더) · `briefing/models.py`(SignalRow · Disclosure · Flag · Briefing · SendResult · RunRecord · `dart_link()`) — 테스트 19개 (TDD)
- [x] `briefing/state.py` — `BriefingState` + **`briefings`·`dart_calls` reducer(`operator.add`)** · `FetchItem` · 상수(게이트값·상태값·10회/60초/limit 40) · 테스트 6개
- [x] `briefing/nodes.py` — 노드 전부를 **빈 통과 함수**로 (PLAN §1-1 구조 그대로) · `route_gate` · `fan_out`(Send) · `_status_of`/`record_run`/`finalize`는 실구현
- [x] `briefing/graph.py` — `build_graph(overrides)`: 노드·엣지 · `route_gate` 조건부 · `gate→wait→gate` 사이클 · `Send` fan-out · `RetryPolicy` · `recursion_limit=40` (아래 ①)
- [x] `briefing/main.py` — `--date` · `--dry-run` · `--force` · `--if-not-briefed` → 초기 상태 → `invoke()`. 스텁 상태로 START→END 완주 (`status=no_signals` · exit 0) · `store.py` 연결·`briefed_today()` · 테스트 11개
- [x] `tests/conftest.py` `wiring()` + `tests/test_graph.py` — ① 게이트 ready/stale/missing 3경로 ② missing 10회 → `record_run` → `finalize(gate_timeout)` ③ **Send N개 → reducer 합류** (+ 0건 직행) ④ `summarize`·`send_email` 실패 시 `record_run` 도달 — 테스트 8개 (아래 ②)
- [x] `supabase/schema.sql`(`ksb_briefings` · `ksb_runs` · CHECK · RLS) + `scripts/apply_schema.py --verify` → 실DB 적용 · **anon SELECT 허용 · INSERT 42501 차단 확인** (트랜잭션 안에서 롤백)
- [x] `store.py` 게이트 조회(`fetch_today_run`) 실구현 → `--dry-run`이 실DB에서 `status=ok data_date=2026-08-25 → ready` 출력 · `gate` 노드 테스트 5개
- [x] `scripts/export_graph.py` → `docs/GRAPH.md` · `ci.yml` · `git init` · README 2종 · 시크릿 스캔 · 첫 푸시 · **CI 녹색** (2026-08-26)

**완료 기준 — 전부 충족 (2026-08-26)**
- 배선 테스트 4종 통과(테스트 총 51개) · 실DB 게이트 동작 · `ksb_*` RLS 검증 · CI 녹색

**구현하며 조정한 것** (2026-08-26)

| # | 항목 | 내용 |
|---|------|------|
| ① | **`gate_timeout` → `record_run` → `finalize`** | PLAN 그림은 `finalize` 직행이었다. "실패해도 기록이 먼저" 원칙에 맞춰 `record_run`을 거친다. PLAN v1.0.1·`graph.png` 갱신 |
| ② | **게이트 확인 11회 · 대기 10회** | "1분 대기 후 재시도 최대 10회" = 마지막 대기 뒤 한 번 더 확인. 안 그러면 마지막 60초가 헛되다 |
| ③ | **fan-out 0건이면 `summarize` 직행** | 조건부 엣지가 빈 `Send` 목록을 돌려주면 LangGraph는 거기서 **조용히** 끝난다 — 문자열 경로를 함께 둔다 |
| ④ | **테스트 스텁이 판정을 건너뛰면 실패가 안 보인다** | `wiring()`의 `record_run` 스텁이 `_status_of`를 건너뛰어 `send_failed`가 안 나왔고, `wait` 스텁이 `attempts`를 안 올려 무한 루프가 났다. 스텁은 로그만 남기고 실제 `record_run`에 위임(dry_run이라 DB 안 탐), `wait`는 자지 않고 `attempts`만 올린다 |
- 상위 `krx-signal-alerts/docs/PLAN.md` §4에 "세 번째 소비자: krx-signal-briefing" 한 줄 — **사용자 확인 후** 커밋

---

## M1 — DART 계층 ★ TDD 핵심

> 규칙표(SPEC F5)는 **초안**이다. 실제 `report_nm` 표본으로 대조한 뒤 확정한다. **키워드 하나를 지워도 테스트가 통과하면 그 규칙은 검증되지 않은 것이다.**

- [x] `tests/fixtures/corpcode_sample.xml` — 정상 · 공백/개행 · 문자 티커 · 비상장 3형(공백 한 칸·빈 태그·태그 없음) · 중복 2형(다른 corp_code → 최신 modify_date · 완전 동일) + `corpcode_error_800.xml`(점검 응답 원문) — **실파일 대조는 미해소 이슈 ⑥**
- [x] `briefing/corp.py` TDD — zip 바이트 → `{stock_code: corp_code}` (`zipfile` · `xml.etree`) · `PK` 매직으로 오류 본문(800) 가려냄 · 중복은 `modify_date` 최신 우선(순서 무관) · 테스트 12개
- [x] `briefing/dart.py` — `urlopen` mock 테스트: `000` · **`013`=0건 정상** · `020`=한도 · `800`=점검 · 5xx · 타임아웃 · 1회 재시도(키 오류 010/011은 재시도 없음) · **예외 메시지·stdout에 키가 없다**(N7, `mask()`) · `total_count>100` 경고 · 테스트 16개
- [x] `scripts/sample_reports.py` — 최근 90일(≈60거래일) 신호 종목 **153개** × 120일 창 → `report_names.txt`(**352종 · 3,000건**) + `list_sample.json` · `store.fetch_signal_tickers_since()` · **corpCode.xml 실파일 대조 완료**(미해소 ⑥ 해소) — 2026-08-29
- [x] `briefing/flags.py` — `normalize()` TDD: 접두 `[…]` 전부 제거(`정정` 계열만 `corrected`) · 공백 제거 · `ㆍ`→`·` · **괄호는 유지**(래퍼 안 키워드) · 뒤 `  (설명)`을 `note`로 분리 — 테스트 15개
- [x] `briefing/flags.py` — 규칙표 20개(🔴 12 · 🟡 8) + `match()`/`classify()` TDD: **규칙당 양성 1 + 헷갈리는 음성 1**(표본 실제 제목) · 표본 없는 규칙은 테스트 실패 · 자회사 강등 · 등급 최댓값 · `none` · 실표본 352종 회귀 — 테스트 60여 개
- [x] `briefing/flags.py` — 리츠 예외(D9) TDD: 이름에 `리츠` + 유상증자결정 → 🟡 · 리츠가 아니면 🔴 · 리츠라도 CB는 🔴
- [x] `fetch_one` 노드 실구현 — `existing` 있고 `--force` 아니면 DART 생략 · corp_code 없으면 `unknown` · 실패 시 `level='error'`(raise 금지) · 창 `[run_date−30, run_date]`(`FetchItem.run_date` 추가) · **13줄** (20줄 테스트로 고정) · `Briefing.from_signal()` — 테스트 7개
- [x] `scripts/dryrun.py` — 신호 × DART 판정(종목당 1회 조회 후 30일 창으로 절단) → `docs/dryrun_m1.md`(등급 분포 · 전략별 · 규칙별 · 🔴 전 건 원문 링크). **상위 데이터가 9거래일뿐**(08/17 배포)이라 60거래일은 불가 — 165건으로 측정 (아래 「측정 기록」)
- [x] **SPEC F5 규칙표 확정 (v1.2)** — 🔴 12종목 **DART 원문 본문 대조**(`download_document`) → **11/12 정확**. CB 3건 규모 확인(160·400·120·100억), 유상증자 6건 전부 실제 희석, 최대주주변경 1건은 실질 경영권 이전(SK이터닉스 30.7%→43.2%). **오탐 1건**: 한화갤러리아 — ㈜한화 인적분할로 명의만 변경(지분율 54.29% 동일) → 규칙 유지하고 SPEC에 알려진 오탐 유형으로 기록

**완료 기준 — 전부 충족 (2026-08-29)**
- 규칙표가 실표본 3,000건과 대조됨 · 드라이런 분포 🔴 8%·🟡 8%·none 84% · 일 호출 ≈19회
- 15건 동시 `Send`에서 `020` **0회**
- **🔴 원문 손검증 11/12 정확** (오탐 1건은 알려진 유형으로 기록)

---

## M1b — MCP 계층 (v2.0 · SPEC §2-3)

> **MCP 서버는 데이터 소스다** (N14). 도구 순서는 코드가 정하고 LLM에는 도구를 주지 않는다. 응답은 표본 JSON으로 mock, 실제 Node 기동은 CI 통합에서만.

- [x] `requirements.txt`에 `mcp>=2.1,<3` 추가(사용자 확인 2026-08-29) · 로컬 stdio 기동 확인 3종 · **버전 고정: korean-dart-mcp@0.10.1 · @isnow890/naver-search-mcp@1.0.50 · korea-stock-mcp@1.4.1** (아래 「측정 기록」)
- [x] `briefing/mcpc.py` — 서버별 전용 루프 스레드 위 stdio 세션 1회 · 동기 `call()`/`call_json()` · 스레드 락 · 예외 4종(`Start`·`Call`·`Protocol`·`Unavailable`) · **세션 파손 시 죽음 표시 + 이후 즉시 실패**(R18) · 필수 키 없으면 띄우지 않음 · 서버에 필요한 키만 전달 · 레지스트리(`get`·`close_all`, 실패 캐시) · 실서버 통합 확인 — 테스트 17개
- [x] `tests/fixtures/mcp_search_disclosures.json` · `mcp_anomaly.json` · `mcp_insider.json` · `mcp_stock_corp_code.json` · `mcp_stock_error_nokey.txt` — 실제 응답 표본 수집 (삼성전자). naver·KRX 표본은 키 발급 후
- [x] `briefing/dart_mcp.py` — `parse_*`(순수) + `fetch_disclosures`/`fetch_anomaly`/`fetch_insider` · `Disclosure.from_dart_item`을 REST·MCP 공통 매핑으로 · 인자 고정 `all_pages+include_corrections`(REST와 61=61 실측) · `Anomaly`·`Insider` 모델 · 계약 테스트 16개 + **실서버 MCP≡REST 통합 테스트**(`MCP_INTEGRATION=1`, 통과)
- [x] `flags.py` — 🟡 `insider_sell_cluster`: 제목 규칙이 아니라 `Insider.sell_cluster` 입력으로 붙는 플래그(`insider_flag`, `classify(insider=…)`) · 근거(매도 건수·인원·순변동주식)를 `report_nm`에 · `INSIDER_SAMPLES` 5종(sell/strong_sell → 🟡, buy/strong_buy/none → 없음) · 🔴를 내리지 않음 — 테스트 9개
- [x] `schema.sql` — `ksb_briefings.anomaly jsonb` + **`insider jsonb`**(매도 군집 근거 렌더용) `alter table … add column if not exists` · 실DB 적용·열 확인 · `Briefing.anomaly`/`insider` · `to_row()`(없으면 null = '못 봄') — 테스트 3개
- [x] `fetch_one` 재구성 — `enrich.briefing_for()`(MCP 공시 → REST 폴백 → 판정 → 보조 신호 개별 생략) 호출로 **12줄** · `Briefing.source`/`skipped`(열 아님, 렌더·detail용) · `enrich.run_detail()` 집계 · 테스트 12개(폴백 경로 · 둘 다 실패 → error · anomaly만 실패 · insider 🟡 승격)
- [x] ~~`stock_mcp.py`~~ → **`store.fetch_flows()`로 대체** (D14 v2, 2026-08-29): 상위 `krx-stock-charts`에 **SPEC F8 신설**(pykrx `get_market_cap_by_ticker` 1회 → `ksc_tickers.mktcap`·`list_shrs`·`mktcap_d`, 실DB 2,767종목 수집 완료) → 우리는 `ksc_bars.a` 5일 합과 함께 **SQL 한 번**으로 읽는다. **KRX OPEN API 키·korea-stock-mcp 불필요.** 상위 테스트 129개 통과
- [x] `load_market` 노드(**배치 1회 SQL**) → `fan_out`이 `FetchItem.flow`로 분배 → `fetch_one` ③ 부착 · `ksb_briefings.flow` 저장 · 조회 실패·상위 미수집 시 전 종목 `skipped += flow`(`⚠ 시세 참고 생략`) · 종목만 없는 경우와 구분 · 테스트 8개 · `GRAPH.md` 재생성 · 실DB 확인(삼성전자 15,551,101억 · 가비아 6,113억)
- [x] CI `setup-node`(20.19) + `~/.npm/_npx`·`~/.korean-dart-mcp` 캐시 · **`mcp` 잡 신설**(`scripts/mcp_probe.py --require dart` — 공시 서버는 필수, 키 없는 서버는 건너뜀, 포크 PR은 스킵) · `dryrun.py --source mcp|rest|both`로 **경로 대조** · 기동 시간 「측정 기록」

**완료 기준 — 충족 (2026-08-29)**
- MCP·REST 공시 목록 일치 (통합 테스트 `MCP_INTEGRATION=1`) · 폴백 경로 테스트 · 로컬 웜 기동 1.0초
- CI `mcp` 잡 녹색 (2026-08-29). **기동 시간은 Secrets 등록 후(M4) 측정** — 지금은 키가 없어 두 서버 모두 건너뛴다

---

## M1c — 뉴스 (v2.0 · F11)

- [x] `npx -y @isnow890/naver-search-mcp@1.0.50` **기동 확인** (2026-08-29): 패키지 실행 0.9초 · 자격증명 쌍을 주면 **0.5초 기동 · 도구 18개**. `mcpc.Spec`을 `required` → **`credentials`(쌍 목록 중 하나면 기동)**로 바꿔 **HUB 쌍·개발자센터 쌍 둘 다 지원** · `.env.example`에 두 경로 자리 · 테스트 3개
- [x] **네이버 키 `.env` 등록·검증** (2026-08-29) — 개발자센터 키(ID 20자·Secret 10자). 처음 `NCP_APIGW_*` 변수에 들어와 있어 **HTTP 401**(`Not Exist Client ID`) → `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로 이동하니 정상(total 18,765). MCP 경유 `search_news` 실호출 확인 · `mcp_news.json` 표본 확보. **Secrets 등록은 M4**
- [x] `tests/fixtures/mcp_news.json` 표본 (실호출)
- [x] `briefing/news_mcp.py` — `search_news` → `NewsItem` · `<b>` 태그·HTML 엔티티 제거 · `pubDate`(RFC 822) 파싱 · **검색어에 `주가` 부착**(A/B 실측) · 제목·링크 없는 항목 제외 · 계약 테스트 18개
- [x] `fetch_one` ④ — `enrich.news_for()` · **등급 `none`일 때만** 호출 · 실패는 `skipped += news`(0건과 구분) · `ksb_briefings.news` 저장 · `run_detail`에 뉴스 집계 · 테스트 5개 · **실서버 확인**(DL 5건 부착)
- [x] `render.py` 전체 — 조건 5줄 + 등급 + 공시(**전 항목 링크**) + 보조 신호 + 💰시세 + **📰 뉴스 블록** + 💬요약 + `⚠ 생략` 표기 · 제목 4종 · 🔴 상단 요약 · HTML 이스케이프·앵커 · **금지어 검사는 우리 문장만**(공시·뉴스 제목은 원문 예외) · 공시 목록 길이 제한(플래그는 예외) — 테스트 29개
- [x] `summary.py` — `build_input`(제목·날짜·등급만, **뉴스 제목 포함**, 종목당 12건 상한) · 시스템 프롬프트 · JSON 스키마 · `validate()`(금지어·80자·미지 티커·빈 값) — 테스트 16개
- [x] **실메일 1통 발송·손검증** (2026-08-29): 08/26 신호 15건 · 🔴 2(씨피시스템 CB, 엔투텍 CB 4건) · none 13건 전부 뉴스 부착 · 시세 15/15 · `status=ok` · `ksb_briefings` 15행·`ksb_runs` 기록 확인. 본문 24,497자 → **18,012자**(공시 길이 제한 후)

**완료 기준**: 위 둘 + 검증 3종

---

## M2 — 본문·저장·발송

- [x] `briefing/render.py` — 종목 블록 TDD: 조건 5줄(`evidence.conditions` 그대로) + 구분선 + 등급 + 공시 목록 + **원문 링크 필수**(N2) · `evidence` 키 누락 시 줄만 비움(R8) — 테스트 16개. **R8 구멍 2개를 이 테스트가 잡았다**(아래 트러블슈팅)
- [x] `render.py` — 🔴 상단 요약 블록 · 전략/종목 **순서 = 상위 메일과 동일** · HTML 이스케이프(`&` 이름) · 평문 대체본
- [x] **레이아웃 재설계** (2026-08-29 시안 합의 · `docs/DESIGN.md`) — 인덱스 표 + 종목 카드 · 제목이 곧 링크 · 이모지→색 칩 · 압축 카드 · **길이 예산**(N15)
- [x] `render.py` — 제목 4종(F8): 정상 · `[브리핑 없음]` 0건 · 데이터 지연 · `⚠ 공시 조회 실패 N건` 접두
- [x] `render.py` — **금지어 테스트**(N1): `추천`·`매수`·`매도`·`보류`·`호재`·`악재`·`목표가`·`손절`·`여력`·`이탈`·단독 `없음` — `report_nm` 원문은 검사 제외 · `none` 문구는 "최근 30일 공시 중 확인된 위험 유형 없음"
- [x] `render.py` — `⚠ 요약 생성 실패` 줄 · `unknown`(DART 코드 미확인) · `error`(공시 조회 실패) 표기
- [x] `briefing/store.py` — `ksa_signals` 대상 조회(F2) · 기존 `ksb_briefings` 읽기 · `ksb_briefings` upsert · `ksb_runs` insert — mock 테스트
- [x] `briefing/notify.py` — SMTP mock · STARTTLS · `certifi` · 평문+HTML multipart
- [x] `load_signals` · `load_corps` · `render` · `persist` · `send_email` · `record_run` · `finalize` 노드 실구현 (각 20줄 이내)
- [x] **실DB + 실발송 1회** (`--date`로 어제 신호, 요약 없이) → 두 번째 메일 도착 · 받은편지함 확인 · **재실행 시 DART 재호출 없음**(N6)

**완료 기준**
- 요약 없는 브리핑 메일이 실제로 도착 · 금지어·링크 테스트 통과 · 멱등 확인

---

## M3 — Claude 요약

> LLM은 **있으면 좋은 층**이다. 이 마일스톤의 절반은 "없어도 메일이 간다"를 증명하는 데 쓴다.

- [x] `briefing/summary.py` — `build_input()` TDD: 공시 0건 종목 제외 · 제목·날짜·등급만(본문 없음)
- [x] `summary.py` — 시스템 프롬프트 상수(사실만 · 입력에 있는 공시만 · 80자 · 금지어 · 등급 불변 · 한국어) + 출력 JSON 스키마 `{"items":[{"ticker","summary"}]}`
- [x] `summary.py` — `validate()` TDD: 금지어 · 80자 초과 · 입력에 없는 티커 · 빈 문자열 → 해당 항목만 버리고 사유 반환
- [x] `briefing/llm.py` — `claude-opus-5` · 공식 SDK · 구조화 출력(`output_config.format`) · `max_tokens=4096` · 타임아웃 60초 · 재시도 2회. 예외를 `LlmUnavailable`(키 없음)·`LlmError`(그 밖) 둘로 좁힌다
- [x] `tests/test_llm.py` — SDK mock: 성공 · API 오류 · 타임아웃 · `stop_reason == "refusal"` · **키 없음(R12)** → 전부 `summary_error`, 예외 불투과
- [x] `summarize` 노드 — 기존 `summary` 있으면 건너뜀(`--force` 제외) · `ksb_runs.summary_n` · `llm_tokens` 기록
- [x] 실호출 1회 → **15종목 전부** 원문 대조. **사실 오류 1건 발견·수정**(아래 트러블슈팅) → 재호출에서 0건. 토큰·비용 「측정 기록」
- [x] **키를 빼고** 실호출·실발송 → `요약 생략: ANTHROPIC_API_KEY 없음` · 메일 도착 · `status='ok'` · `summary_n=0` (2026-08-30)

**완료 기준**
- 요약 있는/없는 두 메일 모두 도착 · `validate()` 통과 · 비용 기록

---

## M6 — 신호 검증 (v3.0) ★ 목적 재정의

> SPEC v3.0(§2-4·§2-5)에 따라 **공시 나열 → 신호 검증**으로 바꾼다.
> 근거: 공시 101건 중 65%가 정형 · 15종목 중 13종목이 정형뿐 · 뉴스 적합도 64% (2026-08-30 실측).
> **M4(배포)보다 먼저 한다** — 지금 형태로 매일 자동 발송해 봐야 읽히지 않는다.

### 먼저 고칠 것 (v3.0 이전에 드러난 결함)

- [ ] **재실행이 뉴스·보조 신호를 지운다** — `store.fetch_briefings()`가 `news`·`anomaly`·`flow`를 복원하지 않는데 `persist`가 그 브리핑을 그대로 덮어쓴다. 2026-08-30 실행으로 15종목의 뉴스·anomaly·flow가 **실제로 소실**됐다. 복원 열을 늘리고 회귀 테스트를 둔다
- [x] ~~상위 KRX 로그인 실패~~ **해소** (2026-08-30, 상위 `ffe7fac` — 사용자 수정). 실패는 08-18부터였고 08-30 실행에서 `KRX 로그인 완료` 확인. R22 정정

### 재료 늘리기 (F15·F17·F11 v2)

- [ ] `briefing/routine.py` — **정형·정기 공시 판정 규칙표**(F16) TDD: 양성·유사음성 표본. 플래그된 공시는 절대 접지 않는다
- [ ] `dart_mcp.fetch_event()` — `get_corporate_event(corp, event_type, bgn_de, end_de)`(F15). **규칙 id → event_type 매핑표**를 테스트로 고정. 대응 없는 규칙은 제목만
- [ ] `models.EventBody` — 발행금액·자금용도·사모여부·이자율·전환가·**오버행 비율**·전환청구기간·미상환잔액. `ksb_briefings.bodies` jsonb 신설
- [ ] `news_mcp` v2 — 검색어 `{종목명}` · `sort="sim"` · **제목에 종목명 없으면 버림** · **`description` 저장**(F11 v2). A/B 재측정 기록
- [x] **상위 `krx-stock-charts` SPEC F14 신설·구현 완료** (2026-08-30, 상위 `b957a4a`) — `ksc_investor_flows`는 **넓은 형태**로 바꿨다(투자자별 행이면 1년 3.4M행, `ksc_bars`가 이미 2.4M행). 시장2 × 투자자**5**(`기관합계`·`외국인`·`기타외국인`·`개인`·`기타법인`) = **하루 10회**. `외국인합계`는 이 엔드포인트가 거부해 `외국인`+`기타외국인`으로 만든다. **실수집 31거래일 · 81,852행 · 2,693종목**(07-14~08-27). 상위 테스트 12개 추가·141개 통과
- [ ] 거래일에 상위 워크플로가 F14를 실제로 수집하는지 확인 (2026-08-31) — 08-30 실행은 휴장일이라 로그인만 확인됐다
- [ ] `store.fetch_flows_30d()` — 15종목 × 30일을 SQL 한 번으로(F17). 없으면 생략 + `⚠ 수급 생략`

### 판정과 서술 (F18·F19)

- [ ] `briefing/verdict.py` — **판정(정합/불일치/무관) + 점수(0~100)** 순수 함수(F18) TDD. 산식을 테스트로 고정. **무엇을 못 보고 낸 점수인지** 함께 돌려준다
- [ ] `summary.py` v2 → `analysis.py` — 입력에 공시 본문·수급·판정·점수를 넣고, 출력은 **종목당 최대 2,000자 근거 서술**(F19). 프롬프트에 "2,000자는 상한이지 목표가 아니다"(R21)
- [ ] `validate()` v2 — 금지어(N1 v2) · 길이 · 미지 티커 · **판정 단어가 코드 판정과 다르면 버림** · 숫자 대조(위험 유형 건수·오버행 비율)
- [ ] `summarize` 노드 → `analyze` — 20줄 유지. 실패해도 판정·점수·근거 데이터는 나간다

### 본문과 전문 페이지 (F20·F7 v3)

- [ ] `render.py` v3 — 인덱스 표에 **판정·점수 열** 추가 · 정형 공시 접기 한 줄 · 공시 본문 표 · 수급 30일 요약 · **분석 발췌 2~3줄 + 전문 링크** · **점수 한계 문구**(F18, 절대 접히지 않음)
- [ ] `page.py` — 전문 페이지 생성(F20). **공개 링크로 두지 않는다**(R7 v2). 실패해도 메일은 간다
- [ ] `docs/DESIGN.md` v2 — 판정·점수·수급이 들어간 레이아웃 시안 → **사용자 합의 후 구현**

### 검증

- [ ] 실호출 1회 → **5종목 손검증**: 판정·점수가 근거와 맞는가 · 입력에 없는 사실 0건 · 토큰·비용 재측정(입력이 커졌다)
- [ ] 두 메일 대조 — 요약 있음 / LLM 죽음 / 수급 없음 세 경우 모두 메일 도착 · `status='ok'`

**완료 기준**
- 씨피시스템 08/26이 `주요사항보고서(전환사채권발행결정)` 한 줄이 아니라 **오버행 5.10% · 자금용도 시설 · 공시일 외국인 -11.4억**으로 읽힌다
- 판정·점수는 코드가 내고 테스트로 고정 · LLM이 바꾸지 못함 · 점수 한계 문구가 항상 붙는다

---

## M4 — 자동화·배포

> ⚠ **배포 전 보안 점검 필수** (SPEC N9 · 워크스페이스 CLAUDE.md)

- [ ] `briefing.yml` — `repository_dispatch: types: [alert-completed]` · 예비 cron `05 00 * * 0-4`(`--if-not-briefed`) · `workflow_dispatch(date, dry_run, force)` · `timeout-minutes: 25` · `permissions: contents: read` · `concurrency: briefing`
- [ ] `main.py --if-not-briefed` — 오늘 `ksb_runs` 있으면 로그 한 줄 + 종료 0 (테스트)
- [ ] 이 리포 Secrets 8종 등록 (`DART_API_KEY` · `ANTHROPIC_API_KEY` · `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` · `SUPABASE_DATABASE_URL` · `GMAIL_ADDRESS` · `GMAIL_APP_PASSWORD` · `RECIPIENTS`)
- [ ] Actions `workflow_dispatch --dry-run` 완주 → 실발송 1회
- [ ] **보안 점검** — 보안 리뷰 · 히스토리 시크릿 스캔(`sk-ant-` · `github_pat_` · DART 40자 hex) · 로그 마스킹(`***`) · 워크플로 권한 · `ksb_*` RLS
- [ ] **[상위 리포] PAT 생성** — fine-grained · Repository access: `krx-signal-briefing`만 · Contents: Read and write · 만료 1년 → 상위 Secrets `BRIEFING_DISPATCH_TOKEN`. **만료일을 아래 미해소 이슈 ①에 기록**
- [ ] **[상위 리포] `alert.yml` 마지막 단계 추가** (SPEC F0, `if: always()`) — **사용자 확인 후** 커밋 · 상위 CLAUDE.md·TASKS.md에 한 줄
- [ ] 트리거 시험 ① — 상위 `workflow_dispatch` 수동 실행 → 이 워크플로가 **1분 안에** 시작 · 브리핑 메일 도착
- [ ] 트리거 시험 ② — 이미 브리핑된 날 예비 cron(또는 수동 `--if-not-briefed`) → no-op 종료
- [ ] 트리거 시험 ③ — 상위 배치 없는 날(주말) 수동 실행 → 10분 뒤 `gate_timeout` 실패 · 깃허브 실패 알림 도착
- [ ] **연속 5거래일 관찰** — 두 메일 순서 · 도착 간격 · 요약 품질 · `ksb_runs` 상태 · 스팸함 → 「측정 기록」

**완료 기준**: SPEC §9 1~8 전부 (5거래일 도착 · 🔴 손검증 · 드라이런 분포 · 금지어/링크 · 트리거 3경로 · 받은편지함 · LLM 유무 · 검증 3종 + GRAPH.md 최신)

---

## M5 — 마무리

- [ ] `README.md` (영어) · `README_KO.md` (한국어) · 상호 링크 · 그림 3장 포함
- [ ] `docs/GRAPH.md` 최신 확인 — 설계도 `graph.png`와 대조, 다르면 이유 기록
- [ ] 워크스페이스 `CLAUDE.md` 프로젝트 표 갱신(배포됨 · 리포 · 날짜)
- [ ] 이 문서 「측정 기록」·「미해소 이슈」 정리 · SPEC 변경 이력 마감
- [ ] 메모리 갱신

---

## 측정 기록

| 항목 | 값 | 일자 |
|------|-----|------|
| M1 표본 — 신호 종목 153개(90일) × 120일 창 → `report_nm` 352종 · 3,000건 · DART 154회 | 최다: 임원ㆍ주요주주특정증권등소유상황보고서 506 · 대량보유(일반) 160 · 분기보고서 149. 규칙 관련: `[기재정정]주요사항보고서(유상증자결정)` 21 · `주요사항보고서(유상증자결정)` 8 · `유상증자결정(종속회사의주요경영사항)` 7 · `[기재정정]주요사항보고서(전환사채권발행결정)` 15 · 최대주주변경 1 · `기타시장안내(관리종목지정우려종목)` 2 · `불성실공시법인지정예고` 2 | 2026-08-29 |
| M1 표본 — 접두 분포 | `[기재정정]` 432 · `[첨부정정]` 25 · `[발행조건확정]` 6 · `[첨부추가]` 5 · `[정정제출요구]` 2 | 2026-08-29 |
| M1 표본 — 120일 창에서 100건 초과 종목 | 1개(corp 00162461, 186건) — 30일 창에서는 재확인 | 2026-08-29 |
| M1 드라이런 (2026-08-29) — 최근 90일 신호 **165건 · 9거래일 · 하루 18.3건** · 153종목 · DART 154회 · 020 **0회** | 🔴 13 (8%) · 🟡 13 (8%) · none 139 (84%) · unknown **0** · error 0. 전략별: VCP 97(🔴9·🟡9) · MTF 66(🔴3·🟡4) · 눌림목 2(🔴1). 규칙별 플래그: cb 10 · rights_issue 8 · treasury_sale 7 · lawsuit 6 · controller_change 4 · admin_warning 2 · rights_issue(자회사) 2. 하루 예상 호출 ≈ 19회 | 2026-08-29 |
| M1b MCP 기동 (2026-08-29, 로컬 Node 22 · mcp 2.1.1) | korean-dart-mcp@0.10.1 **콜드 10.9초 / 웜 0.6초**, 도구 18 · korea-stock-mcp@1.4.1 1.4 / 0.5초, 도구 8 · naver-search-mcp@1.0.50 **키 없으면 기동 거부**. 도구 호출: search_disclosures 0.1초(페이지 20건 → `all_pages` 필요) · disclosure_anomaly 2.3초 · insider_signal 0.4초 | 2026-08-29 |
| M1b 시세 경로 전환 (2026-08-29) | 세 경로 비교 후 **상위 DB 경유 채택**: ① pykrx 직접(키 불필요·호출 1회·의존성 +pykrx) ② **상위 수집 → 우리는 SQL**(채택) ③ korea-stock-mcp(KRX OPEN API 키 필요·≤18회). 상위 `update --update`에 pykrx 1회가 늘고, 우리 쪽 외부 호출은 0회가 됐다. 실측: 상위 2,767/2,769종목 수집, `ksc_tickers.mktcap` null 2종목 | 2026-08-29 |
| M1b dart_mcp ≡ REST (2026-08-29) | `search_disclosures` 인자별: all_pages만 53 · **all_pages+include_corrections 61** · page size=100 61 · days=30+all_pages 53 — REST 61과 일치하는 조합으로 고정. 실서버 통합 테스트 통과(집합·정렬 동일) | 2026-08-29 |
| **M3 요약이 건수를 지어냄 (2026-08-30)** | 첫 실호출에서 씨피시스템 요약이 「최근 30일 위험 유형 **2건**」이라 적었다 — 실제 플래그는 **1건**. 원인은 모델이 아니라 **입력**이었다: `build_input`이 `level: "red"`만 보내고 **어느 공시가 걸렸는지·몇 건인지를 넣지 않아** 짐작하게 만들었다. 두 곳을 고쳤다 — ① 걸린 공시에 `flag`를 붙이고 `risk_count`를 사실로 넣는다(프롬프트도 "세지 말고 `risk_count`를 쓰라") ② `validate()`가 요약이 적은 건수를 실제와 다시 대조해 다르면 그 항목만 버린다. 재호출 결과 씨피시스템 1건·엔투텍 4건으로 정확 | 2026-08-30 |
| **M3 실호출 측정 (2026-08-30)** | 15종목 1회 일괄: 입력 **7,975** · 출력 **992** 토큰 → **$0.0647**(약 91원). 평일 20일 기준 **월 약 1,800원**. 검증에서 버려진 항목 0건. 노드 경유 실행은 뉴스가 빠져 5,478 토큰 | 2026-08-30 |
| **M3 두 메일 대조 (2026-08-30)** | 같은 날 세 번 실행 — 요약 있음(15종목·5,561토큰) / **키 없음**(`summary_n=0`·`summary_error`) / 요약 복구(15종목·5,478토큰). 세 번 다 `status=ok`, 메일 도착. **LLM이 죽어도 메일은 간다**를 실물로 확인 | 2026-08-30 |
| **M2 evidence 방어 구멍 (2026-08-29)** | 종목 블록 TDD를 쓰다 R8이 **모델 층에서 깨져 있는 것**을 발견. ① `evidence`가 `null`이면 `.get`에서 `AttributeError` ② 종가가 `"8,420"`(쉼표 낀 문자열)이면 `int()`가 `ValueError`. 둘 다 **그날 메일이 통째로 사라지는** 실패다. `SignalRow.ev`·`_as_int`·`_as_float`로 막고, `conditions`가 목록이 아닌 경우·조건 항목의 키 누락까지 테스트로 잠금 (모델 6개 + 렌더 10개) | 2026-08-29 |
| **M2 레이아웃 재설계 (2026-08-29)** | 첫 실메일이 `<pre>` 한 덩어리라 읽히지 않음 → **Claude Design 3안 시안 → 추천안(인덱스 표 + 카드) 사용자 합의** → 구현. 눈에 보이는 글자수 **18,012 → 6,539자**. `docs/DESIGN.md` 신설, SPEC F7 v2 · F7b · N15 | 2026-08-29 |
| **M2 Gmail 클리핑 (2026-08-29)** | 시안 1차가 **149,971 bytes**로 Gmail에 잘림(한계 102,400). 스타일을 클래스로 접고(→111,339) 평문 대체본을 위험 종목만 펼치게 바꿔 **78,269 bytes·여유 24%**. `test_real_sized_mail_fits_in_a_gmail_message`가 실제 `EmailMessage` 크기로 잠금 | 2026-08-29 |
| M2 실메일 1통 (2026-08-29 12:49) | 08/26 신호 15건 · DART 15회 · 출처 전부 mcp · 생략 0 · anomaly clean 7·watch 7·warning 1 · **none 13종목 전부 뉴스 부착** · 발송 1명 성공. 본문 18,012자(제한 전 24,497) | 2026-08-29 |
| M2 네이버 429 (2026-08-29) | fan-out 15종목이 몰리자 3건에서 **HTTP 429**(초당 제한 — 일일 25,000과 별개). 호출 간 0.35초 간격 + 429면 1.5초 후 1회 재시도로 해소 | 2026-08-29 |
| M1c 뉴스 검색어 A/B (2026-08-29) | 종목명 단독 vs `종목명 주가` — **가비아** 2/3 → 3/3 · **핑거** 0/3(핑거푸드·음악) → 전환사채 취득 기사 포착 · **DL**(2글자)은 둘 다 시황 기사. `주가` 부착 채택, 남은 노이즈는 R17대로 나열만 | 2026-08-29 |
| M1c naver-search-mcp (2026-08-29) | 기동 **1.0초 · 도구 18개**(search_news 등 검색 8 + datalab 9 + find_category). 서버 로그에 `Using 네이버 개발자센터 (2027-06-30 지원 종료 예정)` — 어느 쌍으로 붙었는지 스스로 알린다. 실호출: 가비아 뉴스 total 18,765 · 응답 0.x초 · 항목에 `<b>` 태그와 HTML 엔티티가 섞여 온다(정제 필요) | 2026-08-29 |
| M1 🔴 손검증 (2026-08-29) | 12종목 원문 대조 **11/12 정확**. 오탐 1: 한화갤러리아(인적분할 — 지분율 54.29% 불변). 부수 확인: `최대주주변경`은 `최대주주등소유주식변동신고서(최대주주변경시)`와 **짝으로 와서 같은 사건이 2줄** → M2 렌더에서 묶기 검토 | 2026-08-29 |
| M1b 경로 대조 (2026-08-29) | `dryrun.py --source both` 8종목 — **MCP ≡ REST 불일치 0건**. DART 호출 17회(양쪽 각 8 + corpCode 1) | 2026-08-29 |
| M1b MCP 기동 (로컬 웜, 2026-08-29) | korean-dart-mcp **1.0초**(18도구) · korea-stock-mcp 0.8초(배치 제외) · naver 키 없어 건너뜀 · 총 4.9초. 도구 호출: search_disclosures 0.1초 · disclosure_anomaly 2.2초 · insider_signal 0.4초 | 2026-08-29 |
| M1b mcpc 실서버 통합 (2026-08-29) | dart 웜 기동 1.0초 · 스레드 4개 동시 호출 직렬화 정상 · naver 키 없음 → `McpStartError`로 띄우지 않음 · stock `get_corp_code` OK, `get_stock_trade_info`는 KRX 키 없음 `McpCallError`. **`search_disclosures(all_pages=true)`는 mode=batch, 삼성전자 30일 53건 — 페이지 모드 total_count 61과 다르다(정정 포함 여부 추정) → `dart_mcp.py`에서 `include_corrections`로 REST 61건과 일치시킬 것** | 2026-08-29 |
| M1 드라이런 — 눈에 띈 것 | ① 같은 CB 결정이 원문 + `[기재정정]` ×2로 3~4줄 (엔투텍·빛과전자) → M2 렌더에서 정정 묶음 표시 검토 ② 최대주주변경은 `최대주주변경` + `…변동신고서(최대주주변경시)` 두 제목이 짝으로 옴 (한화갤러리아·SK이터닉스) | 2026-08-29 |
| M1 — 하루 DART 호출 수 · `020` 발생 여부 | — | |
| M1 — 규칙표 변경 내역(추가·삭제 키워드) | — | |
| M3 — 요약 1회 입력/출력 토큰 · 비용 | — | |
| 상위 배치 실제 시작 시각 (cron 08:20) | 08:41 · 08:42 · 08:41 · 08:45 · 08:43 KST — 5일 연속 **20분 이상 지연** | 2026-08-26 |
| 상위 하루 신호 (전체 / 메일 / 카카오) | 44/15/10 · 47/21/10 · 41/13/10 · 48/21/10 · 40/14/10 | 2026-08-26 |
| M4 — 상위 완료 → 브리핑 시작 지연(초) · 상위 메일 → 브리핑 메일 간격 | — | |
| M4 — 5거래일 관찰(도착 · 등급 · 요약 품질) | — | |

---

## 트러블슈팅 기록

| # | 증상 | 원인 | 해결 |
|---|------|------|------|
| 2 | `corpCode.xml`이 175바이트, `BadZipFile` (2026-08-29 토 10:39) | **DART 시스템 점검** — HTTP 200으로 `<status>800</status>` XML을 준다. zip이 아니다 | `dart.py`는 `PK` 매직 바이트/`<status>`로 오류 본문을 먼저 가려낸다. 응답 원문을 `tests/fixtures/corpcode_error_800.xml`로 보관. 토요일 오전 점검이라 평일 08:45 실행과는 무관해 보이나, 평일 점검 여부는 미해소 이슈 ⑥ |
| 1 | 08/25 신호 44건인데 `sent_email=true`가 0건 (2026-08-26 연결 테스트) | 상위 배치가 `sent_email` 열을 저장하지 않는다 — 카카오 상위 10건만 `sent_kakao=true`. 메일 발송 집합은 `suppressed=false` 전체(15건 = `ksa_runs.sent_email_n`) | SPEC F2를 `suppressed = false`로 변경(v1.1.1). 코드에서 `sent_email`을 쓰지 않는다 |

| 5 | CI `mcp` 잡이 두 번 실패 (2026-08-29) | ① Secrets에 `DART_API_KEY`가 없어 dart가 안 뜸 ② `--require`의 **기본값이 `["dart"]`**라 인자를 안 줘도 요구했다 | 키가 있을 때만 `--require dart`를 붙이도록 워크플로 분기 + `--require` 기본값을 빈 목록으로. **키 없음은 CI 실패 사유가 아니다** — 그 층이 없는 것뿐이다(D15) |
| 3 | MCP 프로브가 `tool.inputSchema`·`result.isError`에서 `AttributeError` (2026-08-29) | **MCP 파이썬 SDK 2.x는 snake_case** (`input_schema`·`is_error`). 1.x 문서·예제와 다르다 | 2.x 필드명 사용. `mcpc.py`에 계약 테스트로 고정 |
| 4 | korea-stock-mcp `get_stock_trade_info` 인자 오류 | README는 `isuSrtCd/fromDate/toDate`인데 실제 스키마는 `basDdList/market/codeList` | 실스키마 기준. `mcpc.list_tools()`로 기동 시 스키마를 확인해 로그 |

### 미리 알고 있는 함정 (상위·선행 프로젝트에서 확인됨)

- **LangGraph 병렬 노드는 reducer 없이 상태를 조용히 덮어쓴다** — `Send` fan-out 결과를 `briefings: Annotated[list, operator.add]`로 받지 않으면 마지막 하나만 남고 예외도 안 난다. `test_graph.py` ③이 유일한 방어선
- **I/O 노드는 예외를 밖으로 내지 않는다** — `fetch_one`·`summarize`·`send_email`이 raise하면 `record_run`에 못 가 실패 기록이 사라진다
- **Supabase REST는 1,000행에서 조용히 잘린다** — 여기서는 일 15행이라 무관하지만 `ksa_signals` 이력 조회(드라이런)는 psycopg로
- **티커는 숫자가 아니다** — `0126Z0`. `corpCode.xml`의 `stock_code`도 문자열로 비교
- **`create table if not exists`는 마이그레이션이 아니다** — 열 추가는 `alter table … add column if not exists`
- **의존성이 역할을 바꾸면 파일도 옮긴다** — psycopg는 런타임 의존성(`requirements.txt`)
- **깃허브 cron은 정시를 보장하지 않는다** — 주 경로는 dispatch라 무관, 예비 cron은 수십 분 밀릴 수 있음
- **stdout에 키를 찍지 않는다** — DART는 키가 URL 쿼리에 실린다. 예외 메시지에 URL이 통째로 들어가기 쉽다
- **OpenDART `013`은 오류가 아니다** — "조회된 데이터가 없습니다" = 공시 0건
- **DART 제목은 흔들린다** — `유상증자결정` / `유상증자 결정` / `[정정]유상증자결정`. 정규화 없이 매칭하면 미탐
- **Opus 5는 `stop_reason == "refusal"`을 낼 수 있다** — content를 읽기 전에 stop_reason부터
- **pip/npm은 이 디렉토리에서** — 워크스페이스 루트 오설치 사례 있음

---

## 미해소 이슈

| ID | 내용 | 상태 |
|----|------|------|
| ① | **dispatch PAT 만료** — fine-grained PAT 최장 1년. 만료일: (M4에서 기록). 만료 시 상위 `alert.yml` 마지막 단계가 실패로 알려 주고, 예비 cron 09:05가 그날 브리핑을 대신 돌린다 (SPEC R13) | 🔜 M4에서 기록 |
| ② | 상위 anon 키 범위 이슈(상위 SPEC R4) 상속 — `ksb_*`는 읽기 전용 RLS만 | 인지 (SPEC R6) |
| ③ | 30일 창 밖·보고서 본문 안의 위험은 못 본다 — 문구로 한계를 드러낸다 (SPEC R2). `window_days`로 뒤에 조정 가능 | 의도된 선택 |
| ④ | 15건 동시 DART 요청 허용 여부 미확인 | M1 드라이런에서 확인 |
| ⑤ | 지주·홀딩스 예외 규칙 없음 (D9) — 드라이런에서 오탐 보이면 추가 | M1에서 관찰 |
| ⑥ | ~~`corpcode_sample.xml` 실파일 대조~~ → **해소 (2026-08-29 10:55)**: 118,804건 · 상장 3,988 · 비상장 `' '` · 중복 0 · 문자 티커 58. 토요일 오전 점검(`800`)은 10:39~10:5x 사이에 끝났다. 평일 08:45 점검 여부는 M4 관찰에 포함 | ✅ |
