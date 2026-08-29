# TASKS.md — krx-signal-briefing

> 기준: `SPEC.md` v1.1 · `PLAN.md` v1.0 (2026-08-26)
> 저장소: `daehyub71/krx-signal-briefing` (public) · 트리거: 상위 `alert.yml` → `repository_dispatch` · 예비 cron 평일 09:05 KST
> 체크할 때마다 아래 대시보드를 함께 갱신한다. 마일스톤을 닫을 때는 **ruff · mypy strict · pytest 전부 통과**가 전제다.

---

## 진도율 대시보드

| 마일스톤 | 진도 | % | 태스크 | 상태 |
|----------|------|---|--------|------|
| M0 뼈대 + 걷는 해골 | `██████████` | 100% | 12/12 | ✅ 2026-08-26 |
| M1 DART 계층 ★ TDD | `█████████░` | 90% | 9/10 | 🔄 🔴 손검증 대기 |
| **M1b MCP 계층** (v2.0) | `░░░░░░░░░░` | 0% | 0/10 | 🔜 D12·D13·D15 확정 대기 |
| **M1c 뉴스** (v2.0) | `░░░░░░░░░░` | 0% | 0/5 | 🔜 |
| M2 본문·저장·발송 | `░░░░░░░░░░` | 0% | 0/9 | 🔜 |
| M3 Claude 요약 | `░░░░░░░░░░` | 0% | 0/8 | 🔜 |
| M4 자동화·배포 | `░░░░░░░░░░` | 0% | 0/11 | 🔜 |
| M5 마무리 | `░░░░░░░░░░` | 0% | 0/5 | 🔜 |
| **전체** | `███░░░░░░░` | **30%** | **21/70** | 🔄 M1 |

범례: 🔜 대기 · 🔄 진행중 · ✅완료일

**사용자 준비물 (블로커)**

| 시점 | 항목 | 상태 |
|------|------|------|
| M0 전 | OpenDART 인증키 (opendart.fss.or.kr, 무료·즉시) → `.env` `DART_API_KEY` | ✅ 2026-08-26 연결 확인 |
| M0 전 | 깃허브 리포 `krx-signal-briefing` 생성 (public) | ✅ 2026-08-26 첫 푸시 |
| M3 전 | Anthropic API 키 → `.env` `ANTHROPIC_API_KEY` | ✅ 2026-08-26 연결 확인 |
| **M1b 전** | **D12·D13·D15 확정** (SPEC §2-3). D14는 ✅ 포함 확정(2026-08-29) | ⏳ |
| **M1b 전** | **KRX OPEN API 키** (`KRX_API_KEY`, data.krx.co.kr 등록·승인 ~1일) — korea-stock-mcp용 | ⏳ |
| **M1c 전** | **네이버 NCP API HUB 키** (`NCP_APIGW_API_KEY_ID` / `NCP_APIGW_API_KEY`) | ⏳ |
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
- [ ] **SPEC F5 규칙표 확정** — 표본 대조 결과로 키워드 추가·삭제, 변경 일자·근거를 SPEC에 기록 · 🔴 표본 전 건 원문 링크 손검증

**완료 기준**
- 규칙표가 실데이터 표본과 대조됨 · 드라이런 분포 합리적(전부 🔴도 전부 `none`도 아님) · 일 호출 < 100회
- 15건 동시 `Send`에서 `020`이 없음 — 있으면 순차/`max_concurrency`로 전환하고 PLAN §7에 기록

---

## M1b — MCP 계층 (v2.0 · SPEC §2-3)

> **MCP 서버는 데이터 소스다** (N14). 도구 순서는 코드가 정하고 LLM에는 도구를 주지 않는다. 응답은 표본 JSON으로 mock, 실제 Node 기동은 CI 통합에서만.

- [ ] `requirements.txt`에 `mcp` 추가(사용자 확인 후) · 로컬 `npx -y korean-dart-mcp@<ver>` 기동 확인 · 버전 고정값 결정
- [ ] `briefing/mcpc.py` — stdio 세션 1회 · `call(tool, args, timeout=30)` · 스레드 락 · 실패 예외 · **stdout 오염 시 실패 격리**(R18)
- [ ] `tests/fixtures/mcp_search_disclosures.json` · `mcp_anomaly.json` · `mcp_insider.json` — 실제 응답 표본 수집
- [ ] `briefing/dart_mcp.py` — 응답 → `Disclosure` / `{score, verdict}` / 군집 종류. 계약 테스트 · **REST(`dart.py`)와 같은 종목·같은 창의 공시 목록이 일치**하는 테스트
- [ ] `flags.py` — 🟡 `insider_sell_cluster` 규칙 + SAMPLES
- [ ] `schema.sql` — `ksb_briefings.anomaly jsonb` 추가(`alter table … add column if not exists`) · `Briefing.anomaly` · `to_row()`
- [ ] `fetch_one` 재구성 — MCP 공시 → 폴백 → 판정 → 보조 신호 생략 표기 · 20줄 유지 · 테스트(폴백 경로 · 보조 실패 경로)
- [ ] `tests/fixtures/mcp_stock_trade.json` 표본 · `briefing/stock_mcp.py` — korea-stock-mcp `get_stock_trade_info` → `{mktcap, list_shrs, trdval_5d}` · 응답에 시총·상장주식수가 있는지 **실표본으로 확인**(없으면 SPEC F12 수정) · 계약 테스트
- [ ] `fetch_one` ③에 시세 참고 추가 · `ksb_briefings.flow` 저장 · 키 없음·실패 시 생략 + `⚠ 시세 참고 생략` 테스트
- [ ] CI `setup-node`(20.19) + npm·`~/.korean-dart-mcp` 캐시 · **MCP 3종 기동 시간 측정** · 드라이런 MCP 경로 vs REST 경로 대조 → 「측정 기록」

**완료 기준**: MCP·REST 공시 목록 일치 · 서버를 죽여도 폴백으로 완주 · CI 기동 < 60초

---

## M1c — 뉴스 (v2.0 · F11)

- [ ] 네이버 키 `.env`·Secrets · `npx -y @isnow890/naver-search-mcp@<ver>` 기동 확인
- [ ] `tests/fixtures/mcp_news.json` 표본 · `briefing/news_mcp.py` — `search_news` → `NewsItem` · HTML 태그·엔티티 제거 · 계약 테스트
- [ ] `fetch_one` ④ — 등급 `none`만 · 실패 시 생략 · `ksb_briefings.news` 저장
- [ ] `render` 📰 블록 · `⚠ 뉴스 생략` · 금지어 검사에서 뉴스 제목 원문 예외 · `summary` 입력에 뉴스 제목
- [ ] 키 없이 실행 → 메일 도착 · `none` 종목 뉴스 메일 1통 손검증

**완료 기준**: 위 둘 + 검증 3종

---

## M2 — 본문·저장·발송

- [ ] `briefing/render.py` — 종목 블록 TDD: 조건 5줄(`evidence.conditions` 그대로) + 구분선 + 등급 + 공시 목록 + **원문 링크 필수**(N2) · `evidence` 키 누락 시 줄만 비움(R8)
- [ ] `render.py` — 🔴 상단 요약 블록 · 전략/종목 **순서 = 상위 메일과 동일** · HTML 이스케이프(`&` 이름) · 평문 대체본
- [ ] `render.py` — 제목 4종(F8): 정상 · `[브리핑 없음]` 0건 · 데이터 지연 · `⚠ 공시 조회 실패 N건` 접두
- [ ] `render.py` — **금지어 테스트**(N1): `추천`·`매수`·`매도`·`보류`·`호재`·`악재`·`목표가`·`손절`·`여력`·`이탈`·단독 `없음` — `report_nm` 원문은 검사 제외 · `none` 문구는 "최근 30일 공시 중 확인된 위험 유형 없음"
- [ ] `render.py` — `⚠ 요약 생성 실패` 줄 · `unknown`(DART 코드 미확인) · `error`(공시 조회 실패) 표기
- [ ] `briefing/store.py` — `ksa_signals` 대상 조회(F2) · 기존 `ksb_briefings` 읽기 · `ksb_briefings` upsert · `ksb_runs` insert — mock 테스트
- [ ] `briefing/notify.py` — SMTP mock · STARTTLS · `certifi` · 평문+HTML multipart
- [ ] `load_signals` · `load_corps` · `render` · `persist` · `send_email` · `record_run` · `finalize` 노드 실구현 (각 20줄 이내)
- [ ] **실DB + 실발송 1회** (`--date`로 어제 신호, 요약 없이) → 두 번째 메일 도착 · 받은편지함 확인 · **재실행 시 DART 재호출 없음**(N6)

**완료 기준**
- 요약 없는 브리핑 메일이 실제로 도착 · 금지어·링크 테스트 통과 · 멱등 확인

---

## M3 — Claude 요약

> LLM은 **있으면 좋은 층**이다. 이 마일스톤의 절반은 "없어도 메일이 간다"를 증명하는 데 쓴다.

- [ ] `briefing/summary.py` — `build_input()` TDD: 공시 0건 종목 제외 · 제목·날짜·등급만(본문 없음)
- [ ] `summary.py` — 시스템 프롬프트 상수(사실만 · 입력에 있는 공시만 · 80자 · 금지어 · 등급 불변 · 한국어) + 출력 JSON 스키마 `{"items":[{"ticker","summary"}]}`
- [ ] `summary.py` — `validate()` TDD: 금지어 · 80자 초과 · 입력에 없는 티커 · 빈 문자열 → 해당 항목만 버리고 사유 반환
- [ ] `briefing/llm.py` — `claude-opus-5` · 공식 SDK · 구조화 출력 · `max_tokens=4096` · 타임아웃 60초. **착수 전 `claude-api` 스킬 파이썬 README로 시그니처·refusal fallback 확인**
- [ ] `tests/test_llm.py` — SDK mock: 성공 · API 오류 · 타임아웃 · `stop_reason == "refusal"` · **키 없음(R12)** → 전부 `summary_error`, 예외 불투과
- [ ] `summarize` 노드 — 기존 `summary` 있으면 건너뜀(`--force` 제외) · `ksb_runs.summary_n` · `llm_tokens` 기록
- [ ] 실호출 1회 → 5종목 요약을 원문과 대조: **입력에 없는 사실 0건** · 토큰·비용 「측정 기록」
- [ ] **키를 빼고** 실행 → `⚠ 요약 생성 실패(키 없음)` 붙은 메일 도착 · `status='ok'`

**완료 기준**
- 요약 있는/없는 두 메일 모두 도착 · `validate()` 통과 · 비용 기록

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
