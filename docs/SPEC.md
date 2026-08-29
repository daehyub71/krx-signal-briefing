# SPEC.md — krx-signal-briefing

> **상태: v2.0 검토 중** (2026-08-29). v1.1(D1~D11 확정)에 **MCP 3종 활용 전환**(사용자 지시 2026-08-29)을 §2-3으로 얹었다 — D12~D15 확정 대기.
> v1.1에서 **D3을 `repository_dispatch` 방식으로 변경** (사용자 결정).
> 출발점은 `../../idea_md/stock-mcp-ideas.md`(2026-08-26 검토 문서)다. 그 문서와 달라진 판단은 §2-2에 근거를 남겼다.
> 변경은 이 문서를 먼저 고치고 PLAN → TASKS 순으로 역추적한다 (워크스페이스 CLAUDE.md 진행 원칙 6).

---

## 1. 프로젝트 목표

`krx-signal-alerts`가 평일 08:20 KST에 보내는 아침 신호 메일은 **기술적 조건만** 말한다.
같은 "MTF 정배열 ✓"라도 배경이 수주 공시인지 전환사채 발행 결정인지에 따라 전혀 다르게 읽혀야 하는데,
지금 메일은 그 차이를 보여 주지 않는다.

이 프로젝트는 **그날 발송된 신호 각 건에 최근 30일 DART 공시 사실을 붙인 두 번째 메일**을 보낸다.
차트 조건만으로는 보이지 않는 **물량(유상증자·CB·BW)·지배구조(최대주주 변경)·거래 제약(관리종목)** 위험을
같은 아침에 손에 쥐어 주는 것이 목적이다.

**해결하려는 문제**: 신호 15건의 공시를 매일 아침 DART에서 손으로 찾아볼 수 없다. 조건은 맞는데 사면 안 되는 종목을 걸러 낼 재료를 자동으로 붙인다.

**이 프로젝트가 하지 않는 것** (명시적 비목표)

| 비목표 | 이유 |
|--------|------|
| 매수·매도·보류 판단, 호재·악재 해석 | 상위 프로젝트 비목표 상속. **공시는 사실로만 나열한다** (N1). 판단은 사용자 몫 |
| **수신자 확장** | `RECIPIENTS`는 본인 1명. 해석이 섞인 내용을 남에게 배포하면 유사투자자문업 신고 대상을 건드린다 (R7) |
| MCP **서버** 제작 | 우리가 MCP 서버를 만들지는 않는다. **MCP 클라이언트 호출은 v2.0에서 도입**(§2-3) — 남이 만든 MCP 서버를 배치의 데이터 소스로 쓴다 |
| LLM에 도구(MCP)를 쥐어 주는 에이전트 루프 | 도구 호출 순서는 코드가 정한다(D12). 흐름이 정해져 있는데 LLM이 도구를 굴리면 비용 20~50배(아이디어 §6)에 재현성도 잃는다 |
| 카카오톡 채널 | 본문 200자 상한에 공시 목록이 들어가지 않는다. 브리핑은 메일 전용 |
| 웹 화면 | v1 범위 밖. 다만 `ksb_*` 테이블에 읽기 전용 RLS를 걸어 두어 뒤에 `/signals`가 읽을 수 있게 한다 |
| 상위 프로젝트(`krx-signal-alerts`) **코드·테이블** 수정 | 잘 돌고 있는 알림 로직을 건드리지 않는다. `ksa_*`·`ksc_*`는 **읽기만**. **예외 하나**: `alert.yml` 끝에 이 프로젝트를 깨우는 `repository_dispatch` 단계를 추가한다 (D3, 2026-08-26 사용자 결정). 스크리닝·발송 단계는 그대로다 |
| LLM의 **판단** | LLM은 v1에 들어가되(D7) 공시 3건을 한두 줄로 **압축**하는 일만 한다. 해석·전망·권고를 내지 않는다 (F14·N1·N13) |
| 기관·외국인 **순매수** | korea-stock-mcp에 도구가 없다(D14). F12는 시총·거래대금 참고 표시까지만. 뉴스(F11)는 v2.0에서 v1로 승격 — 단 **등급 `none`인 종목만** (§2-3 D13 ④) |

---

## 2. 결정 사항

### 2-1. 결정 표

| ID | 항목 | 상태 | 결정 | 근거 |
|----|------|------|------|------|
| **D1** | 프로젝트 형태 | **확정** (2026-08-26) | **새 디렉토리 `krx-signal-briefing/` + 새 Git 저장소** | 상위 CLAUDE.md의 핵심 규칙이 "LLM은 없다"·`alert.yml` 무수정. `ksc → ksa` 읽기 전용 체인을 `ksa → ksb`로 한 단 더 잇는 기존 패턴. 대가: 같은 저장소 안에서만 되는 `workflow_run` 트리거를 포기한다 → D3 |
| **D2** | 코멘트 위치 | **확정** (2026-08-26) | **별도 두 번째 메일** (아이디어 §3 안 B) | 기존 메일 본문에 넣으려면 발송 전에 브리핑이 끝나야 하고 그러면 상위 배치를 고쳐야 한다. 알림이 늦게 오는 것보다 두 통 오는 게 낫다 |
| **D3** | 실행 트리거 | **확정 v1.1** (2026-08-26) | **`repository_dispatch`** — 상위 `alert.yml` 마지막 단계가 이 리포에 `alert-completed` 이벤트를 보내고, `briefing.yml`이 그 이벤트로 즉시 실행된다. **DB 게이트(F1)는 유지**, 예비 cron 09:05 KST 추가 | 사용자 결정. 처음 확정안(cron 08:45 + 폴링)과 추천안(cron 08:25 + 폴링)을 **"알람이 나가면 바로 실행"**으로 바꿨다. 얻는 것: 상위 완료 후 **수십 초** 안에 시작, 깃허브 cron 지연이 한 번만 걸린다. 대가: 상위 `alert.yml` 8줄 수정, 대상 리포 쓰기 권한 **fine-grained PAT**를 상위 Secrets에 둔다 (R13). `workflow_run`은 같은 리포에서만 되므로 불가(§2-2 ③) |
| **D4** | 공시 접근 방식 | ~~확정 (2026-08-26)~~ → **v2.0에서 변경 (§2-3 D13)** | ~~OpenDART REST 직접 호출~~ → **korean-dart-mcp `search_disclosures`** (REST는 폴백, D15) | §2-2 ①·② — `corpCode.xml`이 `stock_code`를 담고 있어 티커→corp_code 매핑에 MCP의 캐시가 필요 없고, 무인 배치가 부를 것이 `list.json` 하나뿐이면 MCP는 Node 호스팅만 얹고 데이터는 더 주지 않는다 |
| **D5** | 리스크 표현 | **확정** (2026-08-26) | **🔴/🟡 2단계 + 해당 공시 나열** (점수 없음) | 0~100 점수는 근거를 숨긴다 — 아이디어 §2-1 스스로 "68점만 있으면 아무 판단도 못 한다"고 썼다. 규칙표(F5)가 곧 SPEC이라 TDD가 된다 |
| **D6** | 1단계 범위 | ~~확정 (2026-08-26)~~ → **v2.0에서 변경 (§2-3)** | ~~DART만~~ → **DART + 뉴스(F11) v1 포함**, 수급(F12)은 D14 | 사용자 지시 2026-08-29 |
| **D7** | LLM 도입 | **확정** (2026-08-26) | **v1부터 포함** — 종목당 한두 줄 요약 (F14). 하루 **1회 일괄 호출**, 에이전트 루프 아님 | 사용자 결정(추천안은 "v1 없음"이었다). 흐름이 정해져 있으므로 코드가 데이터를 다 모은 뒤 LLM은 압축에만 쓴다 — 아이디어 §6의 20~50배 비용 차이가 여기서 갈린다. 요약은 **있으면 좋은 층**이다: LLM이 죽어도 메일은 간다 (F14) |
| **D8** | 0건·상위 배치 실패 시 | **확정** (2026-08-26) | **항상 발송** — 0건·데이터 지연인 날도 `[브리핑 없음]` 메일을 보낸다 | 사용자 답 "브리핑 없음"을 이렇게 해석했다 (메일 생략이 아니라 "없음" 메일 발송). 상위 원칙 "침묵을 정상으로 두지 않는다" |
| **D9** | 리츠·지주 예외 | **확정** (2026-08-26) | **리츠만 완화** — 종목명에 `리츠` 포함 시 유상증자결정을 🔴 → 🟡 | 리츠의 유상증자는 정상 자금조달인 경우가 많다. 08/25 신호에 `코람코더원리츠`가 실재. 지주·홀딩스는 v1에서 규칙을 두지 않고 드라이런에서 관찰한다 |
| **D10** | 오케스트레이션 | **확정** (2026-08-26) | **LangGraph를 쓴다** — 상위 프로젝트와 같은 3층 분리·같은 규칙(N3·N11·N12) | 사용자 결정(추천안은 "안 쓴다"였다). 얻는 것: 게이트 재시도 루프·종목별 DART 조회 fan-out·LLM 실패 격리를 그래프로 선언, `docs/GRAPH.md` 자동 생성, 상위와 코드 구조가 같아 오가기 쉽다. 지킬 것: **LLM 호출은 노드 하나**(`summarize`)에 가둔다 — 그래프 어디에서도 LLM이 도구를 굴리지 않는다 |
| **D11** | LLM 제공자·모델 | **확정** (2026-08-26) | **Claude Opus 5 (`claude-opus-5`)** · 공식 `anthropic` SDK · 적응형 사고 · 구조화 출력(JSON) | 대안: 기존 `OPENAI_API_KEY`(cheongyak) 재사용 — 키 발급이 없다는 것 외에 이점이 없다. Claude는 **`ANTHROPIC_API_KEY` 신규 발급**이 필요하다(워크스페이스에 없음). 비용은 하루 1회 일괄 호출(입력 약 5~10K 토큰 · 출력 약 1~2K)이라 어느 쪽이든 **월 수천 원 이내** — 결정 기준은 비용이 아니라 키 관리다. LangGraph 안에서는 SDK를 직접 부른다(`langchain-anthropic` 불필요 — 의존성 최소) |

### 2-2. 아이디어 문서와 달라진 판단 (2026-08-26 조사)

| # | 아이디어 문서 | 확인된 사실 | 결정에 미친 영향 |
|---|---|---|---|
| ① | §7 함정 1 "DART는 티커를 모른다 → MCP의 SQLite 캐시가 필요" | OpenDART `corpCode.xml`(zip, 1회 호출)에 상장사 **`stock_code` 6자리**가 들어 있다. `list.json` 응답에도 `stock_code`가 온다 (공식 가이드 확인) | 티커→corp_code는 코드 10줄. Actions 캐시 불필요 → D4 |
| ② | §5 MCP 클라이언트 위치 (Agent SDK 권고) | 배치가 부를 것은 `list.json` 하나. korean-dart-mcp의 `disclosure_anomaly`는 점수만 주고 근거를 숨긴다 | 배치는 REST + 규칙 기반 플래그 → D4·D5 |
| ③ | §4 `workflow_run: [alert]` | `workflow_run`은 **같은 저장소 안에서만** 동작한다 | 별도 프로젝트면 못 쓴다 → 리포 간 이벤트는 `repository_dispatch`로 (D3 v1.1) |
| ④ | §7 "ANTHROPIC_API_KEY 없음" | 맞다. `OPENAI_API_KEY`는 cheongyak에 있다 | → D7 |

### 2-3. v2.0 — MCP 3종 활용 전환 (2026-08-29 사용자 지시)

사용자 지시: *"korean-dart-mcp · korea-stock-mcp · naver-search-mcp를 활용하는 안으로 수정."*
세 리포를 조사한 결과와 그에 따른 결정 항목이다. **D12~D15는 추천안이며 확정 대기.**

**조사 결과** (2026-08-29, 각 리포 README)

| MCP | 실행 · 전송 | 인증 | 이 프로젝트에 주는 것 | 함정 |
|-----|------------|------|----------------------|------|
| [korean-dart-mcp](https://github.com/chrisryugj/korean-dart-mcp) | `npx -y korean-dart-mcp` · stdio · **Node 20.19+** · MIT | `DART_API_KEY` (있음) | `search_disclosures(corp_code, days)` · `disclosure_anomaly`(0~100 + verdict) · `insider_signal`(임원 매매 군집) · `get_major_holdings` | 첫 실행에 corp 코드 11.6만 건을 SQLite(`~/.korean-dart-mcp`, 24h TTL)로 적재 — **CI는 매 실행이 콜드스타트**. `resolve_corp_code`는 **이름** 기반 |
| [naver-search-mcp](https://github.com/isnow890/naver-search-mcp) | `npx -y @isnow890/naver-search-mcp` · stdio · Node 18+ · MIT | **네이버 키 신규 발급 — 두 경로 중 하나** (서버 `resolveCredentials` 소스 확인, 2026-08-29): ① NCP API HUB `NCP_APIGW_API_KEY_ID`+`NCP_APIGW_API_KEY` (권장, HUB 쌍 우선) ② 네이버 개발자센터 `NAVER_CLIENT_ID`+`NAVER_CLIENT_SECRET` (즉시 발급·카드 불필요, **2027-06-30 종료**). 처리한도 25,000회/일 | `search_news(query, display, sort)` | **두 값은 항상 짝**이어야 한다 — 반쪽이면 기동 거부. 두 자격증명은 서로 호환되지 않는다. PlayMCP 무키 경로는 로그인 세션 기반 → 무인 배치 불가 (403 실측) |
| [korea-stock-mcp](https://github.com/jjlabsio/korea-stock-mcp) | `npx -y korea-stock-mcp` · stdio · Node 18+ · ISC | `DART_API_KEY` + **`KRX_API_KEY`** (KRX OPEN API 등록·승인 ~1일) | **기관·외국인 순매수 도구가 없다.** `get_stock_trade_info`는 일별 시세·거래량(= `ksc_bars`와 중복), 공시 도구는 korean-dart-mcp와 중복 | 새로 주는 데이터가 없다 |

| ID | 항목 | 상태 | 추천 | 근거 |
|----|------|------|------|------|
| **D12** | MCP 클라이언트 방식 | 추천 | **MCP 파이썬 SDK(`mcp` 2.x) stdio 클라이언트** — 우리 코드가 도구를 **정해진 순서로** 부른다. 에이전트 루프 없음, LLM은 요약(F14)만 | 아이디어 §5·§6. 무엇을 부를지 이미 안다. Claude Agent SDK/에이전트 루프는 비용 20~50배 + 비결정적. MCP 서버는 **데이터 소스**이지 판단 주체가 아니다 (N14) |
| **D13** | 도구 배치 | 추천 | ① 공시: `search_disclosures(corp_code, days=30)` → **우리 규칙표(F5)로 판정** ② `disclosure_anomaly` → 점수·verdict를 **보조 표시**(등급은 안 바꿈) ③ `insider_signal` → 매도 군집이면 🟡 새 규칙 `insider_sell_cluster` ④ `search_news` → **등급 `none`인 종목만** 최대 5건 (F11) ⑤ 티커→corp_code는 **기존 `corp.py` 유지** | ②는 아이디어 §2-1 "점수만 보여주지 말 것". ④는 아이디어 §2-2 "공시로 설명 안 될 때만 뉴스". ⑤ `resolve_corp_code`는 이름 기반(동명 위험) + 콜드스타트 적재를 매일 반복 — 우리 방식은 1회 호출·티커 정확 |
| **D14** | 시세 참고(시총·거래대금)를 어디서 | **확정 v2 (2026-08-29 사용자 결정)** — **상위 `krx-stock-charts`가 수집, 우리는 읽기만.** korea-stock-mcp는 **배치에서 제외**(대화형 등록은 자유) | 상위 SPEC에 **F8(시가총액·상장주식수 수집)**을 신설했다 — 상위는 이미 pykrx로 KRX에 붙어 있어 `get_market_cap_by_ticker(date, "ALL")` **1회**로 전 종목 시총을 받아 `ksc_tickers.mktcap`·`list_shrs`·`mktcap_d`에 매일 채운다. 우리는 `ksc_bars.a`(5일 거래대금)와 함께 **SQL 한 번**으로 읽는다 | 처음 안(korea-stock-mcp)은 **KRX OPEN API 키 신규 발급**(승인 ~1일) + 하루 ≤18회 호출이 필요했다. 상위 경유는 **새 키 0개 · 외부 호출 0회**이고, 상위가 쓰는 `KRX_ID`/`KRX_PW`는 이미 있다. 차트 대시보드도 시총을 쓸 수 있다. 대가: 상위 SPEC 변경(2026-08-29 사용자 승인) |
| **D15** | 실패 처리·폴백 | 추천 | korean-dart-mcp 기동·호출 실패 → **`dart.py` REST로 공시 조회 폴백**(이미 구현·테스트됨) → 메일은 간다. anomaly·insider·뉴스는 **있으면 좋은 층** — 실패 시 생략하고 본문에 표기 | 상위 원칙 "실패는 시끄럽게, 단 살아 있는 채널은 간다". npm 레지스트리·Node 기동 실패가 아침 메일을 막으면 안 된다 |

**고정 버전과 실측** (2026-08-29 로컬 기동, MCP 파이썬 SDK 2.1.1)

| 서버 | 고정 버전 | 기동(초, 콜드/웜) | 실측 |
|------|-----------|-------------------|------|
| `korean-dart-mcp` | **0.10.1** | **10.9 / 0.6** (콜드는 corp 덤프 다운로드 포함) | 도구 **18개**. `search_disclosures`는 인자가 `corp`(이름/티커/corp_code 아무거나)·`days`이고 **기본이 페이지 모드(20건/페이지)** — 삼성전자 30일 61건이 4페이지. 전체를 받으려면 `all_pages: true`(+`limit`). `include_corrections`·`final_only`로 정정 포함 여부 제어. 항목 필드는 REST와 동일(`rcept_dt`·`report_nm`·`rcept_no`·`flr_nm`·`rm`). `disclosure_anomaly` → `score`·`verdict`·`flags`·`audit_timeline` (2.3초). `insider_signal` → `summary.signal`(`strong_sell_cluster` 등)·`quarterly_clusters` (0.4초). 서버 배너는 "v0.9.2"로 찍힌다(패키지 버전과 불일치 — 무시) |
| `@isnow890/naver-search-mcp` | **1.0.50** | — | **자격증명이 없으면 기동 자체를 거부**한다(`자격증명이 설정되지 않았습니다`). D15는 "호출 실패"뿐 아니라 "서버 미기동"도 생략 경로로 다뤄야 한다 |
| `korea-stock-mcp` | **1.4.1** | 1.4 / 0.5 | 도구 8개. `get_corp_code(stock_code)`는 KRX 키 없이 동작(티커→corp_code 대안). `get_stock_trade_info`·`get_stock_base_info`는 인자가 **`basDdList`·`market`·`codeList`**(README와 다름)이고 KRX 키가 없으면 `is_error=True` + `There is no KRX API KEY` |

- MCP SDK 2.x는 응답 필드가 **snake_case**다 (`tool.input_schema`, `result.is_error`) — 1.x 문서의 camelCase와 다르다.
- 표본: `tests/fixtures/mcp_search_disclosures.json` · `mcp_anomaly.json` · `mcp_insider.json` · `mcp_stock_corp_code.json` · `mcp_stock_error_nokey.txt` (naver는 키 발급 후).

**v1.1 대비 달라지는 요구사항** — 아래 F4·F4b·F11·F12·N4·N14·R14~R18·§8·§9에 반영했다.

---

## 3. 데이터 소스

### 3-1. Supabase — 읽기 전용으로 재사용

| 테이블 | 용도 | 권한 |
|--------|------|------|
| `ksa_runs` (run_at, data_date, status, …) | **게이트** (F1) — 오늘 신호 배치가 끝났는가, 데이터 기준일은 무엇인가 | SELECT |
| `ksa_signals` (d, strategy, ticker, name, evidence, sent_email, suppressed, …) | 브리핑 대상 (F2) · 조건 5줄 재렌더 (F7) | SELECT |
| `ksc_tickers` | 쓰지 않는다 — 종목명은 `ksa_signals.name`에 스냅샷으로 있다 | — |

**`evidence` 키는 상위 프로젝트의 공유 계약이다** (`krx-signal-alerts/docs/PLAN.md` §4).
이 프로젝트가 **세 번째 소비자**가 된다 — `conditions[].{label, ok, actual}`·`price.{close, change_pct}`·`meta.in_progress`를 그대로 렌더한다.
상위가 키 이름을 바꾸면 여기도 깨진다. 상위 PLAN §4에 소비자로 등재를 요청한다 (M0 태스크).

### 3-2. OpenDART (opendart.fss.or.kr) — 무료 · 인증키 40자 · 일 20,000회

| API | 용도 | 호출 수 |
|-----|------|--------|
| `GET /api/corpCode.xml` | zip 안의 `CORPCODE.xml` → `stock_code` → `corp_code` 사전 (F3) | 하루 **1회** |
| `GET /api/list.json` | `corp_code` · `bgn_de=D−30` · `end_de=D` · `page_count=100` → 공시 목록 (F4) | 신호 건수만큼 (하루 약 15회) |

- 응답 `status`: `000` 성공 · **`013` 조회 결과 없음 = 정상(공시 0건)** · `020` 요청 한도 초과 · `010`/`011` 키 오류 · **`800` 시스템 점검** (2026-08-29(토) 10:39 KST 실측 — `corpCode.xml`도 zip 대신 **HTTP 200 + XML 오류 본문**을 준다. `PK` 매직 바이트 또는 `<status>`로 구분한다).
- `corp_code`를 주면 기간 제한이 없다 (없으면 3개월 제한).
- 응답 필드: `corp_code` · `stock_code` · `corp_name` · `report_nm` · `rcept_no` · `rcept_dt` · `flr_nm`(제출인) · `rm`(비고).
- 원문 링크: `https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}`.
- 하루 호출 약 **16회** — 한도(20,000)의 0.1%. 재시도를 넉넉히 둘 수 있다.

---

## 4. 기능 요구사항

### 4-1. 게이트와 대상

**F0. 트리거 — 상위가 끝나면 즉시 깨어난다** (D3 v1.1)

상위 `alert.yml`의 마지막 단계가 이 리포에 이벤트를 보낸다. `briefing.yml`은 그 이벤트와 예비 cron 두 가지로 시작한다.

| 진입 | 조건 | 역할 |
|------|------|------|
| `repository_dispatch` · `event_type: alert-completed` | 상위 job이 끝나면 **성공·실패와 무관하게** (`if: always()`) 보낸다. 발송이 실패해도 신호는 저장돼 있다 | **주 경로.** 상위 완료 후 수십 초 안에 시작 |
| `schedule` · `05 00 * * 0-4` (평일 09:05 KST) | 예비. 그날 `ksb_runs`가 이미 있으면 **아무것도 하지 않고 정상 종료**(로그 한 줄). 없으면 정상 경로로 진행 | dispatch가 오지 않은 날(PAT 만료·상위 단계 누락)을 받쳐 준다 |
| `workflow_dispatch` | 수동. `date` · `dry_run` · `force` 입력 | 재현·시험 |

상위 쪽 단계 (`krx-signal-alerts/.github/workflows/alert.yml`, M4에서 추가):

```yaml
      - name: 브리핑 워크플로 깨우기 (krx-signal-briefing)
        if: always()                       # 발송이 실패해도 신호는 저장돼 있다
        env:
          GH_TOKEN: ${{ secrets.BRIEFING_DISPATCH_TOKEN }}
        run: |
          gh api repos/daehyub71/krx-signal-briefing/dispatches \
            -f event_type=alert-completed \
            -F 'client_payload[alert_run_id]=${{ github.run_id }}' \
            -F 'client_payload[alert_status]=${{ job.status }}'
```

- 이 단계가 실패하면(토큰 만료 등) 상위 워크플로가 실패로 표시된다 — **일부러 조용히 넘기지 않는다.** 알림 메일은 이미 나간 뒤라 사용자 피해는 없고, 실패 알림이 "브리핑을 못 깨웠다"를 알려 준다 (R13).
- `client_payload`는 참고용이다. 기준일·신호는 이벤트가 아니라 **DB에서 읽는다** (F1) — 이벤트가 잘못 와도 DB가 진실이다.
- 두 진입이 겹쳐도 `concurrency: briefing`으로 직렬화되고, 뒤에 온 쪽은 F9 멱등성 때문에 DART·LLM을 다시 부르지 않는다.

**F1. 게이트 — 신호가 실제로 저장됐는지 확인한다** (D3)

이벤트는 "상위 워크플로가 끝났다"만 말한다. "신호가 저장됐다"는 DB가 말한다. `ksa_runs`에서 `run_at`이 **오늘(KST) 00:00 이후**인 행을 읽는다.

| 결과 | 동작 |
|------|------|
| 행 있음 · `status in ('ok', 'partial_send_failed', 'send_failed')` | 진행. `data_date`를 기준일로 쓴다. 발송 실패여도 신호는 저장돼 있다 (상위는 저장 후 발송) |
| 행 있음 · `status = 'stale_data'` | 신호가 없다. **"브리핑 대상 없음 — 신호 배치가 데이터 지연으로 신호를 만들지 않았습니다"** 메일을 보내고 정상 종료 (D8) |
| 행 없음 | **1분 대기 후 재시도, 최대 10회(10분).** 넘기면 `gate_timeout`으로 **시끄럽게 실패**한다 (N5) |

> dispatch 경로에서는 상위가 이미 끝난 뒤이므로 행이 보통 **첫 시도에** 있다. 10분을 기다리는 것은 상위가 `record_run` 전에 죽은 경우를 잡기 위해서다 — 그때는 이쪽도 실패해야 맞다.
> 예비 cron 경로(09:05)에서 행이 없다는 것은 상위가 그날 아예 돌지 않았다는 뜻이고, 같은 10분 뒤 `gate_timeout`으로 드러난다.

**F2. 브리핑 대상 선정**

`ksa_signals`에서 `d = data_date and suppressed = false`인 행. 상위가 메일에 실은 것과 **정확히 같은 집합**이어야 두 메일이 1:1로 대응한다.

> **2026-08-26 변경** — 원안은 `sent_email = true`였다. 실DB를 보니 상위는 **`sent_email`을 한 번도 `true`로 저장하지 않는다**(카카오 상위 10건만 `sent_kakao=true`). 메일에 실리는 집합은 `suppressed = false` 전체이고, `ksa_runs.sent_email_n`(08/25 = 15)과 정확히 일치함을 확인했다. `sent_email` 열은 판정에 쓰지 않는다.
0건이면 "브리핑 대상 없음 (신호 0건)"을 보낸다 (D8).

### 4-2. 공시 조회와 판정

**F3. 티커 → corp_code 매핑**

`corpCode.xml`을 받아 `stock_code`가 비어 있지 않은 항목만 사전으로 만든다 (상장사 약 3천 개).
- 표준 라이브러리만 쓴다 — `urllib` · `zipfile` · `xml.etree` (N4).
- 매핑에 없는 티커는 **`unknown`(DART 미등록)**으로 표기한다. 오류가 아니다 — 메일에 "DART 코드 미확인"으로 드러낸다.
- 하루 1회 받는다. CI는 콜드 스타트라 캐시하지 않는다 (zip 수 MB, 1회 호출).

**F4. 최근 30일 공시 조회** (v2.0: MCP 경유, D13·D15)

종목마다 korean-dart-mcp `search_disclosures(corp=corp_code, days=30, all_pages=true, limit=100)`를 **1회** 부른다 (페이지 모드는 20건에서 잘린다 — 실측). 응답 항목을 `Disclosure`로 바꾸는 것까지가 I/O 층(`dart_mcp.py`)의 일이고, 판정은 F5 그대로다.
- MCP 서버 기동·호출이 실패하면(타임아웃 30초) **`dart.py` REST(`list.json`)로 폴백**한다. 폴백 여부를 `ksb_runs.detail`에 남긴다.
- MCP도 REST도 실패하면 그 종목은 `error`.

**F4b. 보조 신호** (v2.0 신설, D13 ②·③ — 있으면 좋은 층)
- `disclosure_anomaly(corp)` → `score`(0~100)·`verdict`(clean/watch/warning/red_flag)를 **`ksb_briefings.anomaly` jsonb**에 저장하고 본문에 한 줄 표시. **등급(F5)은 바꾸지 않는다** — 점수는 근거를 숨기므로 참고값이다.
- `insider_signal(corp, start=D−30, end=D)` → 매도 군집(`*_sell_cluster`)이면 🟡 `insider_sell_cluster` 플래그(근거: 매도 건수·인원·순변동주식). 매수 군집은 참고 표시만. 집계값은 **`ksb_briefings.insider` jsonb**에 저장한다 (2026-08-29 구현 시 추가 — 렌더 근거용).
- 둘 다 실패·타임아웃 시 생략하고 `⚠ 보조 신호 생략`을 붙인다. 워크플로는 실패시키지 않는다.

(v1.1 원문 — REST 직접 호출 기준. 폴백 경로로 그대로 유효)
종목마다 `list.json`을 **1회** 부른다 (`page_count=100` — 30일에 100건을 넘는 종목은 없다고 보되, `total_count > 100`이면 로그로 남긴다).
- `013`은 공시 0건으로 정상 처리한다.
- `020`(한도 초과)·5xx·타임아웃은 **1회 재시도** 후 그 종목을 `error`로 표기한다. 메일에는 "공시 조회 실패"로 드러내고, 실행 상태는 `dart_partial`로 남기며 **워크플로는 실패시킨다** (N5). 메일은 이미 갔으므로 부분 성공을 성공으로 위장하지 않는 것만 지키면 된다.
- `pblntf_ty`로 거르지 않는다 — 🔴 유형이 주요사항보고(B)·지분공시(D)·거래소공시(I)에 흩어져 있다.

**F5. 레드플래그 판정 — 순수 함수, TDD 대상** (D5)

`report_nm`에 대한 **키워드 규칙표**로 등급을 매긴다. 한 종목의 등급은 해당 공시 중 **가장 높은 것**이다.

> **2026-08-29 v1.2 — 실표본(153종목 · 3,000건 · 352종 제목)으로 개정.** 원안(v1.1)과 달라진 점은 표 아래에 적었다.
> 코드의 규칙표는 `briefing/flags.py` `RULES`이며 이 표의 사본이다 (N10). 규칙마다 `tests/test_flags.py`에 양성·음성 표본이 있어야 한다.

| 규칙 id | 등급 | 키워드 (정규화 후 부분 일치) | 제외어 | 왜 |
|---------|------|------------------------------|--------|-----|
| `cb` · `bw` · `eb` | 🔴 | `전환사채권발행결정` · `신주인수권부사채권발행결정` · `교환사채권발행결정` | — | 오버행. 주가가 오를수록 전환 물량이 나온다 |
| `rights_issue` | 🔴 | `유상증자결정` | — | 주식 수 증가. **리츠는 🟡**(D9) |
| `controller_change` | 🔴 | `최대주주변경` | `담보제공` | 지배구조. 담보제공계약은 '변경 가능성'이라 🟡 `pledge`로 |
| `admin_issue` | 🔴 | `관리종목지정` | `우려` `해제` | 거래 제약. '우려'는 🟡 `admin_warning` |
| `caution_issue` | 🔴 | `투자주의환기종목지정` | `해제` | |
| `unfaithful` | 🔴 | `불성실공시법인지정` | `예고` `미지정` | '예고'는 🟡 `unfaithful_warning` |
| `delisting` | 🔴 | `상장폐지` | `해소` | |
| `embezzlement` | 🔴 | `횡령` · `배임` | — | 거래정지 사유 |
| `rehabilitation` | 🔴 | `회생절차` | `종결` `폐지` | |
| `audit` | 🔴 | `의견거절` · `범위제한` · `비적정` · `부적정` (**note까지 본다**) | — | 감사의견은 `감사보고서제출              (감사의견 의견거절)`처럼 뒤 설명에만 온다 |
| `trading_halt` | 🟡 | `매매거래정지` | `해제` | 감자·병합 같은 절차성 정지가 많다 — 사실만 |
| `lawsuit` | 🟡 | `소송등의제기` | — | 판결·결정은 제목만으로 방향을 모른다 → 참고 |
| `treasury_sale` | 🟡 | `자기주식처분결정` | — | `…처분결과보고서`는 안 걸린다 |
| `pledge` | 🟡 | `최대주주변경을수반하는주식담보제공` | — | |
| `admin_warning` · `unfaithful_warning` | 🟡 | `관리종목지정우려` · `불성실공시법인지정예고` | — | |
| `market_warning` | 🟡 | `투자경고종목지정` · `투자위험종목지정` | `해제` | |
| `capital_reduction` | 🟡 | `감자결정` | — | |
| (참고) | — | `단일판매ㆍ공급계약체결` · `자기주식취득결정` · `무상증자결정` · `현금ㆍ현물배당결정` · 정기보고서 · 그 외 전부 | | **플래그 없음.** 목록에는 링크와 함께 남는다 |

**정규화** (`flags.normalize`) — 판정 전에 제목을 이렇게 다듬는다:
1. 접두 `[…]`를 전부 뗀다. `[기재정정]`·`[첨부정정]`·`[정정]`·`[정정제출요구]`처럼 **`정정`이 든 접두면 `corrected=True`**; `[발행조건확정]`·`[첨부추가]`는 떼기만 한다.
2. 뒤에 **공백 2칸 이상 + `(설명)`**이 붙으면 `note`로 분리한다 (`주권매매거래정지              (무상증자)`).
3. 공백을 전부 지우고 `ㆍ`를 `·`로 통일한다. **괄호는 남긴다** — 결정 공시는 `주요사항보고서(유상증자결정)`처럼 래퍼 안에 온다.

**강등 규칙** (`match`) — 🔴가 🟡로 내려가는 두 경우:
- **자회사·종속회사 공시** — 제목에 `(자회사의주요경영사항)`·`(종속회사의주요경영사항)`이 있으면. 모회사 주식이 늘어나는 게 아니다. 플래그 `rule`에 `(자회사)`를 붙여 남긴다.
- **리츠의 유상증자** (D9·F6).

**v1.1 → v1.2 변경 사유** (2026-08-29, 표본 `tests/fixtures/report_names.txt`)

| 변경 | 근거 |
|------|------|
| 키워드를 괄호 안에서도 찾는다 | `주요사항보고서(유상증자결정)` 8건 · `[기재정정]주요사항보고서(유상증자결정)` 21건 — 원안의 "괄호 정규화"로는 미탐 |
| 자회사·종속회사 강등 신설 | `유상증자결정(종속회사의주요경영사항)` 7건 — 🔴면 오탐 |
| 접두를 `정정` 계열 4종 + 비정정 2종으로 구분 | `[기재정정]` 432 · `[첨부정정]` 25 · `[발행조건확정]` 6 · `[첨부추가]` 5 · `[정정제출요구]` 2 |
| 제외어 `담보제공`·`우려`·`예고`·`해제`·`종결`·`해소` | 각각 🟡로 내리거나(가능성·예고) 위험이 **끝난** 공시(해제·종결·해소)라 경고하지 않기 위해. 제목은 메일 목록에 그대로 남는다 |
| 🟡에 `trading_halt`·`pledge`·`admin_warning`·`unfaithful_warning`·`market_warning`·`capital_reduction` 추가 | 표본에서 실재 (`주권매매거래정지` 6 · `최대주주변경을수반하는주식담보제공계약체결` 3 · `관리종목지정우려` 2 · `불성실공시법인지정예고` 2) |
| 🟡에서 `주식등의대량보유상황보고서(감소)` 제거 | 제목만으로 증감을 알 수 없다 (일반 160 · 약식 87 — 대부분 무관) |
| `audit`는 note까지 본다 | 감사의견은 제목이 아니라 뒤 설명에 온다 |
| `감사보고서제출` 자체는 플래그 없음 | 정상 제출 3건 — 의견이 note에 없으면 무해 |

**🔴 손검증 결과 — 규칙표 확정** (2026-08-29, 12종목 DART 원문 대조)

`download_document`로 본문을 받아 공시 실물과 대조했다. **11/12 정확** — 규칙표를 이대로 확정한다.

| 종목 | 규칙 | 원문에서 확인한 것 | 판정 |
|------|------|-------------------|------|
| 비비안 | rights_issue | 제3자배정 805,152주 · 50억 · 발행가 6,210원 | ✅ |
| 빛과전자 | cb | 사모 CB **160억** · 전환가 2,560원 · 채무상환 80억 | ✅ |
| 휴림에이텍 | rights_issue | 주주배정후 실권주 일반공모 600만주 (증자전 990만주 → **약 60% 희석**) | ✅ |
| 핑거 | rights_issue | 제3자배정 75만주 · 75억 | ✅ |
| GRT | rights_issue | 제3자배정 171만주 · 71.5억 | ✅ |
| 제이아이테크 | rights_issue | 제3자배정 106만주 · 42.6억 | ✅ |
| 엠엑스로보틱스 | rights_issue | 제3자배정 328만주 · 100억 (증자전 2,0xx만주 → 약 16%) | ✅ |
| 바이오솔루션 | cb | 사모 CB **400억**(250+150, 사모펀드 배정) | ✅ |
| 엔투텍 | cb | 사모 CB **120억** · 전환가 1,519원 | ✅ |
| 씨피시스템 | cb | 사모 CB **100억** · 전환가 5,106원 · 시설자금 | ✅ |
| SK이터닉스 | controller_change | 이클립스㈜가 SK디스커버리 지분 인수 — **30.74% → 43.15%, 실질 경영권 이전** | ✅ |
| 한화갤러리아 | controller_change | ㈜한화 **인적분할**에 따른 변경 — 소유주식수 106,777,959주·지분율 54.29% **그대로** | ⚠ 형식적 |

**알려진 오탐 유형** (규칙을 바꾸지 않는다): 지주사 인적·물적분할에 따른 최대주주 명의 변경.
지분율·주식수가 그대로여서 지배구조 실질 변화가 아니다. 제목만으로는 구분할 수 없고(본문을 받아야 한다),
**"최대주주가 바뀌었다"는 사실 자체는 맞으며** 원문 링크로 5초면 확인된다 — 미탐보다 낫다(R4).
종목당 호출을 늘려 본문을 받는 것은 v1 범위 밖.
- 등급 값: `red` · `amber` · `none`(30일 내 확인된 위험 유형 없음) · `unknown`(DART 미등록) · `error`(조회 실패). **`none`은 "없다"가 아니라 "확인된 항목 없음"이다** — 문구에 그대로 반영한다 (N1).

**F6. 예외 규칙** (D9)

| 대상 | 판정 | 규칙 |
|------|------|------|
| 리츠 | 종목명에 `리츠` 포함 | `유상증자결정` 🔴 → 🟡. 나머지는 동일 |
| 스팩·우선주 | — | 상위 유니버스(F1)가 이미 뺐다. 여기서 다시 판정하지 않는다 |
| 지주·홀딩스 | — | v1 규칙 없음. 드라이런에서 오탐이 보이면 추가 |

### 4-3. 본문·저장·발송

**F7. 본문 생성 — 순수 함수** (N3)

신호 한 건은 아래 형태다. 위 5줄은 `ksa_signals.evidence`를 상위 메일과 **같은 포맷**으로 재렌더한 것이고, 구분선 아래가 이 프로젝트의 산출물이다.

```
코스맥스엔비티 [222040] 8,420원 +1.32%
  ✓ 월봉 종가 > MA20 : 9,500 vs 4,581
  ✓ … (evidence.conditions 그대로)
  ─────────────────────────────────────────────
  📄 공시  최근 30일 3건 · 확인된 위험 유형 없음
           · 08/19 단일판매ㆍ공급계약체결            [원문]
           · 08/07 분기보고서                        [원문]

가비아 [079940] 46,000원 +1.32%
  ✓ …
  ─────────────────────────────────────────────
  🔴 공시  최근 30일 4건 · 위험 유형 2건
           · 08/22 전환사채권발행결정                [원문]  ← 🔴
           · 08/11 최대주주변경                      [원문]  ← 🔴
           · 08/05 분기보고서                        [원문]
```

- 전략별 섹션 순서·종목 순서는 상위 메일과 **같다** — 두 메일을 나란히 놓고 읽는다.
- 🔴 종목을 **맨 위 요약 블록**에 따로 모은다 ("오늘 🔴 2건: 가비아, ○○○"). 본문을 다 읽지 않아도 위험부터 보인다.
- 모든 공시 항목에 **원문 링크 필수** (N2). HTML은 `<a>`, 평문은 URL 그대로.
- 종목명·공시 제목은 HTML 이스케이프한다 (상위와 같은 이유 — `&`가 들어간 이름이 실재).
- 평문 대체본을 함께 보낸다 (스팸 점수).

**F8. 제목**

`[브리핑] 08/26 — 🔴 2 · 🟡 3 · 확인된 위험 유형 없음 10` — **제목만 보고 오늘 열어 볼지** 판단할 수 있어야 한다.
- 0건: `[브리핑 없음] 08/26`
- 데이터 지연: `[브리핑 없음] 08/26 — 신호 배치 데이터 지연`
- 조회 실패 포함: 제목 앞에 `⚠ 공시 조회 실패 N건 · ` 접두

**F9. 저장 — `ksb_briefings` · `ksb_runs`** (§5)

- `ksb_briefings`는 `(d, strategy, ticker)` PK upsert — 재실행해도 같은 결과 (N6). **그날 브리핑이 이미 있으면 DART를 다시 부르지 않는다** (`--force`로 강제).
- `ksb_runs`는 실패해도 반드시 남긴다 — "안 온 게 정상인지 고장인지"를 사후에 가리는 기록.

**F10. 발송 — Gmail SMTP**

상위 프로젝트와 같은 자격증명(`GMAIL_ADDRESS`·`GMAIL_APP_PASSWORD`·`RECIPIENTS`)과 같은 방식(`smtplib` + `email.message`, STARTTLS, `certifi`)으로 보낸다.
발송 실패는 `ksb_runs`에 `send_failed`로 기록하고 워크플로를 실패시킨다.

**F14. LLM 한 줄 요약 — 있으면 좋은 층** (D7·D11)

공시가 **1건 이상**인 종목만 대상으로, 하루 **1회 일괄 호출**로 종목당 한두 줄을 만든다.

| 항목 | 내용 |
|------|------|
| 입력 | 종목별 `{ticker, name, level, flags[], disclosures[](rcept_dt, report_nm, rcept_no)}` — 제목·날짜·등급만. 공시 본문은 넣지 않는다 (v1) |
| 출력 | 구조화 JSON `[{ticker, summary}]`. `summary`는 **80자 이내** 한두 문장 |
| 프롬프트 규칙 | N1 금지어·"사실만, 판단 금지"·"입력에 없는 공시를 만들지 않는다"를 시스템 프롬프트에 그대로 박는다. 등급(🔴/🟡)은 코드가 정한 값을 그대로 쓰고 LLM이 바꾸지 못한다 |
| 검증 (N13) | 응답을 코드가 검사한다 — ① 금지어 없음 ② 80자 이내 ③ 입력에 있는 티커만. 하나라도 걸리면 **그 종목의 요약만 버린다** |
| 실패 처리 | API 오류·타임아웃·파싱 실패 시 **요약 없이 메일을 보낸다.** 메일 상단에 `⚠ 요약 생성 실패` 한 줄, `ksb_runs.detail`에 오류 기록, `status='ok'` 유지(요약은 메일의 성립 조건이 아니다). 단 워크플로 로그에는 남긴다 |
| 멱등 | `ksb_briefings.summary`가 이미 있으면 다시 부르지 않는다 (`--force` 제외) |
| 위치 | 본문에서 등급 줄 바로 아래: `💬 08/22 CB 400억 발행 결정, 08/11 최대주주 변경 — 최근 30일 위험 유형 2건` |
| 호출 | 하루 1회 · 입력 약 5~10K 토큰 · 출력 약 1~2K. **에이전트 루프·도구 호출 없음** — 무엇을 부를지 이미 알고 있으므로 (아이디어 §6) |

**F13. 워크플로**

`briefing.yml` — 진입 3종은 F0. job `timeout-minutes: 25` (게이트 10분 + DART·LLM·발송 + 여유). `permissions: contents: read`. `concurrency: { group: briefing, cancel-in-progress: false }`.
`workflow_dispatch` 입력: `date`(YYYYMMDD) · `dry_run` · `force`. 예비 cron 경로는 `main.py --if-not-briefed` 플래그로 "오늘 `ksb_runs` 있으면 종료"를 구현한다.

### 4-4. 예약 — 2·3단계 (v1 범위 밖)

| ID | 내용 | 붙이는 조건 |
|----|------|------------|
| **F11** → **v1 승격 (v2.0)** | 네이버 뉴스 — naver-search-mcp `search_news(query="{종목명} 주가", display=5, sort="date")`. **검색어에 `주가`를 붙인다** (2026-08-29 A/B 실측: `핑거` 단독은 3/3 무관 기사, `핑거 주가`는 전환사채 취득 기사가 잡힘). **등급 `none`인 종목만**(드라이런 84%). 제목·언론사·날짜·링크를 `ksb_briefings.news` jsonb에 저장하고 본문에 나열, LLM 요약 입력에 포함 | NCP API HUB 키 필요. PlayMCP 경로는 무인 배치 불가(로그인 세션·403 실측). 동음이의 노이즈(R17)는 v1에서 걸러내지 않고 **링크와 함께 사실로 나열**만 한다 |
| **F12** → **v1 (v2.0, D14 v2)** | **상위 DB에서 SQL 한 번**: `ksc_tickers`(시가총액·상장주식수·기준일, 상위 F8) + `ksc_bars.a` 최근 5거래일 합(거래대금) → `ksb_briefings.flow` jsonb에 저장하고 보조 신호 줄에 참고 표시 (`시총 6,113억 · 5일 거래대금 32억 (08/27)`). **순매수는 넣지 않는다** — 어느 소스에도 없다 | 외부 호출 0회 · 새 키 0개. `load_market` 노드가 배치 1회로 읽어 `fan_out`이 종목별로 나눠 준다. 상위가 아직 시총을 안 채웠거나 조회가 실패하면 생략 + `⚠ 시세 참고 생략`. **실측 2026-08-29**: 2,767/2,769종목 수집, 조회 정상 |
| **F14+** | 요약에 공시 **본문** 반영 (`document.xml`로 CB 규모·전환가 등) | v1 요약이 제목만으로 부족하다고 판단될 때. 호출 수가 종목당 +N회가 된다 |

---

## 5. 데이터 모델 — 새로 만드는 것

같은 Supabase 프로젝트에 접두어 **`ksb_`**로 추가한다. `ksa_*`·`ksc_*`는 건드리지 않는다.

```sql
create table if not exists ksb_briefings (
  d            date not null,            -- 신호 기준일 (= ksa_signals.d)
  strategy     text not null,
  ticker       text not null,
  name         text not null default '', -- ksa_signals.name 스냅샷 (조인 없이 렌더)
  corp_code    text,                     -- null = DART 미등록 (F3)
  level        text not null,            -- 'red' | 'amber' | 'none' | 'unknown' | 'error'
  -- 등급을 올린 공시만. 점수가 아니라 "어떤 공시 때문인지"를 남긴다 (D5)
  flags        jsonb not null default '[]'::jsonb,   -- [{rule, level, report_nm, rcept_no, rcept_dt}]
  -- 30일 공시 전체. 메일이 이걸 그대로 렌더한다
  disclosures  jsonb not null default '[]'::jsonb,   -- [{rcept_dt, report_nm, rcept_no, flr_nm, corrected}]
  window_days  integer not null default 30,
  news         jsonb,                    -- F11 (v2)
  flow         jsonb,                    -- F12 (v3)
  summary      text,                     -- F14 LLM 요약. null = 공시 0건이거나 생성 실패
  created_at   timestamptz not null default now(),
  primary key (d, strategy, ticker),
  constraint ksb_briefings_level check (level in ('red','amber','none','unknown','error')),
  constraint ksb_briefings_ticker_format check (ticker ~ '^[0-9A-Z]{6}$')
);

create table if not exists ksb_runs (
  run_at       timestamptz primary key default now(),
  data_date    date,                     -- 게이트가 읽은 상위 data_date. 게이트 실패 시 null
  signal_n     integer not null default 0,
  red_n        integer not null default 0,
  amber_n      integer not null default 0,
  error_n      integer not null default 0,
  dart_calls   integer not null default 0,   -- 일 한도 대비 사용량 기록
  summary_n    integer not null default 0,   -- F14 생성 성공 건수. 0인데 공시 있는 종목이 있으면 LLM 실패
  llm_tokens   integer not null default 0,   -- 입력+출력 토큰 (비용 추적)
  status       text not null,
  detail       jsonb not null default '{}'::jsonb,
  constraint ksb_runs_status check (status in
    ('ok', 'no_signals', 'gate_timeout', 'dart_partial', 'dart_failed', 'send_failed'))
);
```

- RLS: 읽기는 `anon`/`authenticated`에 공개(뒤에 웹이 읽을 수 있게), 쓰기는 `service_role`만 — `ksa_*`와 동일 방식.
- `ksa_signals`로의 외래키는 걸지 않는다 (상위도 `ksc_tickers`에 걸지 않았다 — 이력은 남아야 한다).
- `create table if not exists`는 마이그레이션이 아니다 — 열을 늘릴 때는 `alter table … add column if not exists`를 반드시 더한다 (상위에서 배운 것).
- 규모: 일 15행 × 250거래일 ≈ 연 4천 행. Supabase 잔여 115MB에 영향 없음 (R5).

---

## 6. 제약과 리스크

| ID | 제약 | 영향 | 대응 |
|----|------|------|------|
| **R1** | **OpenDART 인증키 미발급** | 모든 마일스톤의 전제 | 사용자가 발급 (무료, 즉시). M0 완료 조건 |
| **R2** | **30일 창 밖·보고서 본문 안의 위험은 못 본다** | 6개월 전 CB 발행은 안 보인다. 감사의견은 `감사보고서제출` 제목만으로는 모른다 | **없다고 말하지 않는다** — `none`의 문구는 "최근 30일 공시 중 확인된 위험 유형 없음" (N1). 창 길이는 `window_days`로 기록해 뒤에 바꿀 수 있게 |
| **R3** | 상위 지연·순서 역전 | 깃허브 cron은 정시를 보장하지 않는다 | **dispatch 경로는 상위 완료 뒤에만 시작하므로 역전이 없다** (D3 v1.1). 예비 cron 경로는 F1 게이트 10분 재시도. 그래도 없으면 시끄럽게 실패 |
| **R4** | 키워드 규칙의 오탐·미탐 | DART 제목 표기가 흔들린다 | F5 정규화 + M1 실데이터 대조. **미탐이 오탐보다 나쁘다** — 애매하면 🟡로 올려 사람이 보게 한다 |
| **R5** | Supabase 잔여 115MB | — | 연 4천 행. 무시 가능 |
| **R6** | 상위 프로젝트 anon 키 범위 이슈(상위 SPEC R4) 상속 | 같은 Supabase | `ksb_*`에 읽기 전용 RLS만 정확히 걸고 노출을 늘리지 않는다 |
| **R7** | **유사투자자문업 경계** | 해석을 남에게 배포하면 신고 대상 | `RECIPIENTS` 본인 1명 유지. 문구는 사실만 (N1). 비목표로 못박음 |
| **R8** | `evidence` 계약 의존 | 상위가 키를 바꾸면 F7이 깨진다 | 상위 PLAN §4에 소비자로 등재 요청. 렌더 함수는 키 누락 시 해당 줄을 비우고 계속 간다 (메일 전체를 죽이지 않는다) |
| **R9** | 메일이 스팸함으로 | 하루 두 통, 링크가 많다 | 평문 대체본 · 제목에 과장 표현 금지 · 첫 주 스팸함 확인 (완료 기준) |
| **R10** | **LLM 환각·판단어** | 입력에 없는 공시를 지어내거나 "주의"·"호재" 같은 판단어를 쓸 수 있다 | F14 입력을 제목·날짜로 좁힌다 · N13 코드 검증으로 걸린 요약은 버린다 · 요약은 등급을 바꾸지 못한다 · 원문 링크가 항상 옆에 있어 사람이 대조할 수 있다 |
| **R11** | **LLM 장애가 메일을 막는다** | API 다운·키 만료·한도 | F14 — 요약 없이 보낸다. LLM은 `summarize` 노드 하나에 갇혀 있고 그 노드는 예외를 밖으로 내지 않는다 (N5·N11) |
| **R12** | **`ANTHROPIC_API_KEY` 미발급** (D11) | 발급 전엔 요약 없이 돈다 | 키가 없으면 `summarize`를 건너뛰고 `⚠ 요약 생성 실패(키 없음)`으로 드러낸다 — 조용히 빠지지 않는다 |
| **R19** (v2.0 → 해소) | ~~KRX OPEN API 키~~ | **D14 v2로 사라졌다** — 상위가 이미 가진 `KRX_ID`/`KRX_PW`(pykrx)로 수집하므로 새 키가 필요 없다 | 대신 **상위 의존이 하나 늘었다**: 상위 일일 갱신이 시총을 못 채우면 우리 시세 줄이 생략된다(메일은 정상). 상위 `ksc_meta.update.marketCaps`로 확인 가능 |
| **R14** (v2.0) | **npx 콜드스타트** | CI마다 Node 설치 + 두 패키지 다운로드 + korean-dart-mcp corp 코드 11.6만 건 적재 | `setup-node` 캐시 + `~/.korean-dart-mcp`·npm 캐시를 Actions 캐시에 물린다. 기동 시간을 측정해 60초 넘으면 D13 ⑤처럼 corp 적재를 우회하는 방법을 찾는다 |
| **R15** (v2.0) | **네이버 키** | 신규 발급(NCP API HUB). 구 developers 키는 2027-06-30 종료 | M1c 전 발급. 없으면 F11을 건너뛰고 `⚠ 뉴스 생략` |
| **R16** (v2.0) | **업스트림 MCP 변경** | 남의 패키지다 — 도구 이름·응답 형태가 바뀔 수 있다 | 버전 고정(N14) + 응답 형태 계약 테스트(표본 JSON) + 실패 시 폴백(D15) |
| **R17** (v2.0) | **뉴스 노이즈** | 언론사 필터 없음, 종목명 동음이의(`한국알콜` 등) | v1은 걸러내지 않고 사실로 나열. LLM 요약에는 **제목만** 넣고 "입력에 없는 사실 금지"(N13) 유지 |
| **R18** (v2.0) | **MCP 서버 stdout 오염·타임아웃** | stdio는 프로토콜 채널 — 서버 로그가 섞이면 세션이 죽는다 | 서버별 타임아웃 30초 · 실패는 종목 단위로 격리(`error` 또는 생략) · 세션은 배치당 1회 열고 닫는다 |
| **R13** | **dispatch용 PAT** (D3 v1.1) | 상위 리포 Secrets에 이 리포 쓰기 권한 토큰이 생긴다. fine-grained PAT는 **최장 1년**이라 만료되면 상위 마지막 단계가 실패한다. 유출되면 이 리포에 쓸 수 있다 | **fine-grained PAT · 대상 리포 1개만 · 권한 `Contents: write`만** (dispatch 생성에 필요한 최소). 만료 시 상위 워크플로가 **시끄럽게 실패**해 알려 주고, 그날 브리핑은 **예비 cron 09:05가 대신 돌린다** (F0). 만료일을 `TASKS.md` 미해소 이슈에 적어 둔다. 상위 Secrets에 이미 카카오·Gmail 비밀이 있으므로 노출면이 새로 생기는 것은 아니다 |

---

## 7. 비기능 요구사항

| ID | 요구사항 |
|----|----------|
| **N1** | **문구 규칙 — 사실 나열은 되고 판단은 안 된다.** 금지어: `추천` · `매수` · `매도` · `보류` · `호재` · `악재` · `목표가` · `손절` · `여력` · `이탈` · 단독 `없음`(→ `확인된 항목 없음`). 렌더 테스트가 금지어를 잡는다 (공시 제목 원문은 예외 — 이스케이프된 `report_nm` 안의 문자열은 검사에서 뺀다) |
| **N2** | 모든 공시 항목에 DART 원문 링크 필수. 링크 없는 항목은 렌더 테스트 실패 |
| **N3** | **3층 분리 계승** (D10) — 그래프 층(`state.py` · `nodes.py` · `graph.py`)만 LangGraph를 안다. 도메인(`flags.py` 판정 · `render.py` 본문 · `corp.py` 매핑 파서 · `summary.py` 프롬프트 구성·응답 검증)은 순수 함수로 DB·네트워크·LangGraph를 모른다 — 여기가 TDD 대상. I/O(`dart.py` · `store.py` · `llm.py` · `notify.py` · `main.py`)는 부수효과를 아는 유일한 곳. **LangGraph를 걷어내도 도메인 코드가 그대로 살아 있어야 한다** |
| **N4** | **의존성은 다섯** — `langgraph`(D10) · LLM 공식 SDK(D11) · **`mcp`(D12, v2.0)** · `supabase-py` + `psycopg` · `certifi`. HTTP는 `urllib`, zip/XML/메일은 표준 라이브러리. `langchain-*`·`pandas`·`requests`는 쓰지 않는다. **런타임에 Node 20.19+가 추가된다**(MCP 서버 두 개를 `npx -y`로 띄움 — CI는 `setup-node`). 추가는 사용자 확인 후 |
| **N14** (v2.0) | **MCP 서버는 데이터 소스다.** 도구 호출 순서·인자는 코드가 정하고, LLM에는 도구를 주지 않는다. MCP 패키지 버전은 **고정**(`korean-dart-mcp@x.y.z`)하고 올릴 때 계약 테스트를 돌린다 |
| **N5** | 실패는 **시끄럽게** — 게이트 타임아웃·DART 실패·발송 실패는 워크플로를 실패시킨다. 단 종목 하나의 조회 실패로 메일 전체를 막지 않는다 (F4 `error` 표기) |
| **N6** | 멱등 — `ksb_briefings`는 PK upsert. 같은 날 재실행 시 DART를 다시 부르지 않는다 (`--force` 제외) |
| **N7** | 시크릿(`DART_API_KEY` · `ANTHROPIC_API_KEY` · Supabase service key · Gmail 앱 비밀번호 · 상위 리포의 `BRIEFING_DISPATCH_TOKEN`)은 `.env`/깃허브 Secrets에만. 로그에 키를 찍지 않는다. **URL 쿼리에 키가 실리므로 오류 로그에서 URL을 마스킹한다** |
| **N8** | 검증 3종 통과: `ruff check .` · `mypy briefing/` (strict) · `pytest tests/`. 외부 I/O는 테스트에서 전부 mock |
| **N9** | 배포 전 보안 점검 필수 (워크스페이스 CLAUDE.md) — 보안 리뷰 · 시크릿 노출 · CI 권한 · R6 |
| **N10** | 판정 규칙 변경은 SPEC F5 표를 먼저 고친다. 코드의 규칙표는 SPEC의 사본이다 |
| **N11** | **LangGraph 노드는 얇게** — 상태 입출력만. 노드 함수 하나가 20줄을 넘으면 로직이 샌 것. **I/O 노드는 예외를 밖으로 내지 않고 결과를 상태에 적는다** — 실패 판정은 `finalize` 한 곳. 체크포인터는 쓰지 않는다(단발 배치, 상태에 키가 섞이면 디스크에 남는다). 종목별 DART 조회를 fan-out하면 합류 reducer(`operator.add`)를 반드시 둔다 — 상위에서 빠뜨리면 마지막 하나만 남고 예외도 안 나는 것을 확인했다 |
| **N12** | 그래프 구조를 문서로 자동 생성한다 — `draw_mermaid()` → `docs/GRAPH.md`. 그래프가 바뀌면 문서도 바뀐다 (`scripts/export_graph.py`) |
| **N13** | **LLM 출력은 코드가 검증한다** (F14) — 금지어(N1) · 길이 · 입력에 있는 티커만. 검증은 순수 함수(`summary.py`)라 LLM 없이 테스트한다. LLM 호출 자체는 테스트에서 전부 mock |

---

## 8. 기술 스택

| 층 | 스택 |
|----|------|
| 배치 오케스트레이션 | **LangGraph** (D10) — 게이트 재시도 루프 · 종목별 DART 조회 fan-out · LLM 실패 격리를 그래프로 선언 |
| 배치 | Python 3.11+ · 표준 라이브러리 HTTP/zip/XML · `supabase-py` + `psycopg`(상위와 동일) |
| LLM | **Claude Opus 5 `claude-opus-5`** · 공식 `anthropic` SDK · 하루 1회 일괄 호출 (D11) |
| 저장 | Supabase PostgreSQL (기존 프로젝트, 접두어 `ksb_`) |
| 트리거 | 상위 `alert.yml` → `repository_dispatch` (주) · 예비 cron 평일 09:05 KST · DB 게이트 (D3 v1.1) |
| **MCP (v2.0)** | **korean-dart-mcp**(공시·anomaly·insider) · **naver-search-mcp**(뉴스) — `npx -y` stdio, MCP 파이썬 SDK `mcp` 클라이언트, 버전 고정. korea-stock-mcp는 배치에서 제외(D14 v2) |
| 런타임 | Python 3.11 + **Node 20.19+** (CI `setup-node`) |
| 알림 | Gmail SMTP (`smtplib`, 상위와 같은 자격증명) |
| 테스트 | pytest · ruff · mypy(strict) · 외부 I/O(DART·LLM·SMTP·DB) 전부 mock |

---

## 9. 완료 기준

1. 평일 연속 **5거래일**, 신호 메일 뒤에 브리핑 메일이 도착 (신호 0건·데이터 지연인 날의 "브리핑 없음" 포함)
2. 🔴로 판정된 **모든 건**의 원문 링크를 열어 규칙과 일치하는지 확인 — 오탐 0건이 목표, 있으면 F5 표 수정
3. 최근 **60거래일 드라이런**에서 등급 분포가 합리적 (전부 🔴도, 전부 `none`도 아님) · `unknown`(DART 미등록) 비율 기록
4. 금지어 테스트(N1)·링크 필수 테스트(N2) 통과 · 일 DART 호출 **100회 미만**
5. **트리거 3경로 확인** — ① 상위 수동 실행 → dispatch로 이 워크플로가 1분 안에 시작 ② 예비 cron이 이미 브리핑된 날 no-op으로 끝남 ③ 상위 배치 없는 날 수동 실행 → 10분 뒤 `gate_timeout` 실패
6. 메일이 받은편지함에 들어오는 것 확인 (R9)
7. **LLM 요약**: 5거래일 요약 전 건이 N13 검증을 통과하고, 원문과 대조해 **입력에 없는 사실이 0건** · LLM 키를 일부러 빼고 돌렸을 때 `⚠ 요약 생성 실패`가 붙은 메일이 도착하는 것 확인 (R11·R12)
8. 파이썬 검증 3종 통과 · `docs/GRAPH.md` 최신 (N12) · 배포 전 보안 점검 완료 (N9)
9. **(v2.0)** CI에서 MCP 서버 2종 기동·호출 성공, 기동 시간 기록 · korean-dart-mcp를 일부러 죽였을 때 REST 폴백으로 메일 도착 · 네이버 키를 빼고 돌렸을 때 `⚠ 뉴스 생략`으로 메일 도착 · `none` 종목에 뉴스가 붙은 메일 1통 손검증

---

## 10. 참고 — 선행 프로젝트·문서

| 대상 | 관계 |
|------|------|
| `../krx-signal-alerts/` | **데이터 공급자.** `ksa_runs`·`ksa_signals`를 읽기만 한다. `evidence` 계약(PLAN §4)·발송 방식(`notify/email.py`)·3층 분리(CLAUDE.md)를 그대로 따른다. 코드는 가져오지 않고 다시 쓴다 |
| `../idea_md/stock-mcp-ideas.md` | 이 SPEC의 출발점. §3(코멘트 위치)·§8(문구 경계)·§9(단계)는 그대로 채택, §4(트리거)·§5(MCP 클라이언트)·§7 함정 1은 §2-2대로 수정 |
| `../krx-strategy-alerts/docs/PROPOSAL.md` §5-A | PlayMCP 무인 배치 불가(403) 실측 — F11에서 네이버 MCP 경로를 쓰지 않는 근거 |
| OpenDART 개발가이드 | `corpCode.xml` (DS001/2019018) · `list.json` (DS001/2019001) — 필드·오류코드는 §3-2 |

---

## 11. 변경 이력

| 일자 | 버전 | 내용 |
|------|------|------|
| 2026-08-26 | v0.9 | 최초 작성. **D2(별도 메일)·D4(REST 직접, MCP 없음)·D6(DART만) 사용자 확정.** D1·D3·D5·D7~D10 추천안 제시. 아이디어 문서 대비 달라진 판단 4건을 §2-2에 기록 |
| 2026-08-26 | v0.95 | **D1·D3·D5·D8·D9 추천안대로 확정. D7 → LLM v1 포함, D10 → LangGraph 사용으로 사용자가 추천안을 뒤집음.** F14를 v1로 승격(일괄 1회·실패 시 요약 없이 발송), N3 재작성·N11~N13 신설, R10~R12 신설, `ksb_runs`에 `summary_n`·`llm_tokens` 추가, 완료 기준 7 추가. **D11(LLM 제공자) 신설 — 확정 대기** |
| 2026-08-26 | **v1.0 확정** | **D11 확정 — Claude Opus 5 `claude-opus-5` + 공식 `anthropic` SDK.** D1~D11 전부 확정. 준비물: OpenDART 키(R1) · Anthropic 키(R12) |
| 2026-08-29 | **v2.0.2** | **D14 재확정 — 시세는 상위 DB에서 읽는다** (사용자 결정). 상위 `krx-stock-charts`에 **SPEC F8 신설**(pykrx 1회로 시총·상장주식수 수집 → `ksc_tickers`), 우리는 `ksc_bars.a`와 함께 SQL 한 번으로 읽는다. **korea-stock-mcp·KRX OPEN API 키 불필요** → R19 해소, `briefing/stock_mcp.py` 삭제. F12·§8·§9 갱신 |
| 2026-08-29 | v2.0.1 | ~~D14: korea-stock-mcp 포함~~ → v2.0.2에서 대체됨 |
| 2026-08-29 | **v2.0 검토** | **MCP 3종 활용 전환** (사용자 지시). §2-3 신설: 조사 결과(korea-stock-mcp에 순매수 도구 없음) + D12~D15 추천안. D4·D6 변경, F4 MCP 경유 + REST 폴백, F4b 보조 신호(anomaly·insider), F11 뉴스 v1 승격, N4·N14·R14~R18·§8·§9 갱신. **D12~D15 확정 후 v2.0 확정** |
| 2026-08-29 | **v1.2 확정** | 🔴 12종목 DART 원문 손검증 **11/12 정확** → F5 규칙표 확정. 알려진 오탐 1종(지주사 인적분할發 최대주주 변경)을 기록하고 규칙은 유지 |
| 2026-08-29 | v1.2 | **F5 규칙표 개정** — 실표본(153종목 · 3,000건)으로 래퍼 부분 일치 · 자회사 강등 · 접두 6종 · 제외어 · 🟡 6규칙 추가 · 대량보유 제거. 드라이런 165건: 🔴 8% · 🟡 8% · none 84% · unknown 0 · 020 0. **🔴 13건 손검증 뒤 확정** |
| 2026-08-26 | v1.1.1 | 실DB 확인 반영 — **F2 대상 조건을 `suppressed = false`로 변경** (상위가 `sent_email`을 저장하지 않음). 상위 배치 실측: cron 08:20이지만 실제 시작 **08:41~08:45 KST**(5일 연속 20분 이상 지연) — D3 dispatch 방식의 근거가 됨 |
| 2026-08-26 | **v1.1** | **D3 변경 — `repository_dispatch`** (사용자 결정, 추천안은 cron 08:25 + 폴링이었다). F0 신설(진입 3종 · 상위 `alert.yml` 단계), F1 재시도 1분×10, F13 재작성, R3 갱신, **R13(PAT) 신설**, N7·§8·완료 기준 5 갱신. 비목표 "상위 무수정"에 `alert.yml` 예외 명시 |
