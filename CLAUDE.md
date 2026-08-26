# CLAUDE.md — krx-signal-briefing

워크스페이스 규칙(`../CLAUDE.md`)을 따르며, 아래는 이 프로젝트 고유 규칙이다.

**작업 시작 전 `docs/SPEC.md` → `docs/PLAN.md` → `docs/TASKS.md` 순으로 읽는다.** (UI가 없어 DESIGN.md는 없다.)

## 개요

`krx-signal-alerts`가 평일 아침 보낸 신호 각 건에 **최근 30일 DART 공시 사실**(🔴/🟡 등급 · 해당 공시 · 원문 링크 · Claude 한 줄 요약)을 붙여
**두 번째 메일**로 보낸다. 상위 `alert.yml`이 끝나면 `repository_dispatch`로 즉시 깨어난다.

- **상위 프로젝트의 읽기 전용 소비자다.** `ksa_signals`·`ksa_runs`는 SELECT만, `ksc_*`는 아예 읽지 않는다. 쓰는 곳은 `ksb_*`뿐.
- 상위 코드·테이블을 고치지 않는다. 예외는 `alert.yml` 마지막의 dispatch 단계 하나 (SPEC F0).
- 배치 층: `briefing/` (Python + **LangGraph**) → Supabase `ksb_*` (service_role로 쓰기). 웹은 없다.
- 상위와의 접점은 **`ksa_signals.evidence` 키뿐**이다 (상위 PLAN §4 공유 계약 — 우리는 세 번째 소비자).

### LangGraph 3층 분리 — 상위와 같은 규칙

| 층 | 파일 | 규칙 |
|----|------|------|
| 그래프 | `state.py` · `nodes.py` · `graph.py` | LangGraph를 아는 **유일한** 층 |
| 도메인 | `corp.py` · `flags.py` · `render.py` · `summary.py` · `models.py` | **LangGraph·DB·HTTP·LLM을 import하지 않는다.** 순수 함수. 여기가 TDD 대상 |
| I/O | `dart.py` · `llm.py` · `store.py` · `notify.py` · `config.py` · `main.py` | 부수효과를 아는 유일한 곳. 테스트는 전부 mock |

- **노드는 20줄을 넘지 않는다.** 넘으면 도메인 로직이 새어 들어온 것이니 도메인 모듈로 옮긴다.
- **LLM 호출은 `summarize` 노드 하나에만 있다.** 그래프 어디에서도 LLM이 도구를 굴리지 않는다 — 하루 1회 일괄 호출이 전부다.
- **테스트는 도메인 함수를 직접 부른다.** 그래프 테스트는 연결·분기·합류만 본다.
- **LangGraph를 걷어내도 도메인 코드가 그대로 살아 있어야 한다.**

### 문구 규칙 (SPEC N1) — 이 프로젝트의 가장 큰 리스크

**사실 나열은 되고 판단은 안 된다.** 메일 본문·LLM 프롬프트·LLM 출력 검증 세 곳에 같은 규칙을 박는다.

| 써도 되는 말 | 쓰면 안 되는 말 |
|---|---|
| `최근 30일 공시 중 확인된 위험 유형 없음` | `리스크: 없음` |
| `08/22 전환사채권발행결정` + 원문 링크 | `오버행 주의 — 진입 보류` |
| `단일판매ㆍ공급계약체결 (08/20)` | `호재. 상승 여력 있음` |

금지어: `추천` `매수` `매도` `보류` `호재` `악재` `목표가` `손절` `여력` `이탈` 단독 `없음`. `render` 테스트가 잡는다 (공시 제목 원문은 예외).
**`RECIPIENTS`는 본인 1명.** 늘리면 유사투자자문업 경계를 건드린다 (SPEC R7).

## Supabase 테이블

| 테이블 | 접두어 | 이 프로젝트의 권한 |
|--------|--------|-------------------|
| `ksa_signals` · `ksa_runs` | `ksa_` (krx-signal-alerts 소유) | **SELECT만. 절대 쓰지 않는다** |
| `ksb_briefings` · `ksb_runs` | `ksb_` (이 프로젝트 소유) | 읽기·쓰기 |

스키마 원본은 `supabase/schema.sql` — 재실행해도 안전하다(멱등). 열을 늘릴 때는 `alter table … add column if not exists`를 반드시 더한다.

## 실행

```bash
source venv/bin/activate

python -m briefing.main                        # 오늘 기준 브리핑 + 메일
python -m briefing.main --dry-run              # 발송·저장 없이 결과만 출력
python -m briefing.main --date 20260825        # 특정 기준일 재현
python -m briefing.main --force                # 기존 브리핑·요약이 있어도 다시 만든다 (DART·LLM 재호출)
python -m briefing.main --if-not-briefed       # 예비 cron용 — 오늘 이미 돌았으면 no-op

python scripts/apply_schema.py                 # ksb_* 스키마 적용 (멱등)
python scripts/dryrun.py --days 60             # 과거 60거래일 신호 × DART 판정 → 등급 분포 (발송·저장·LLM 없음)
python scripts/sample_reports.py               # 실제 report_nm 표본 수집 → tests/fixtures/
python scripts/export_graph.py                 # 그래프 → docs/GRAPH.md (구조 변경 시 반드시 재실행)
```

## 검증 (태스크·마일스톤 완료 시 전부 통과 필수)

```bash
ruff check .        # 1. 린트
mypy               # 2. 타입 체크 (strict — files는 pyproject.toml)
pytest tests/ -v    # 3. 테스트
```

## 자격증명

`.env`는 `.gitignore` 대상 — **절대 커밋 금지**. `.env.example`은 키 이름만 담는다.

| 키 | 용도 |
|----|------|
| `DART_API_KEY` | OpenDART. **URL 쿼리에 실린다** — 예외 메시지·로그에 URL을 통째로 찍지 않는다 |
| `ANTHROPIC_API_KEY` | Claude 요약 (F14). 없으면 요약 없이 돌고 메일에 `⚠ 요약 생성 실패(키 없음)`이 붙는다 |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_DATABASE_URL` | 상위와 같은 값. service key는 RLS를 우회한다 |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `RECIPIENTS` | 상위와 같은 값 |
| (상위 리포) `BRIEFING_DISPATCH_TOKEN` | fine-grained PAT — 이 리포 1개 · Contents write · 1년. 만료일은 `docs/TASKS.md` 미해소 이슈 ① |

## 이 프로젝트에서 조심할 것

- **`Send` fan-out 결과는 reducer로 받는다** — `briefings: Annotated[list, operator.add]`를 빼먹으면 마지막 하나만 남고 예외도 안 난다 (상위에서 실증). `tests/test_graph.py` 합류 테스트가 유일한 방어선. 지우지 말 것.
- **I/O 노드는 예외를 밖으로 내지 않는다** — `fetch_one`·`summarize`·`send_email`이 raise하면 `record_run`에 못 가 실패 기록이 사라진다. 실패 판정은 `finalize` 한 곳.
- **LLM은 있으면 좋은 층이다** — 죽어도 메일은 간다. `summary_error`를 적고 `⚠ 요약 생성 실패`를 붙인다.
- **LLM 출력은 코드가 검증한다** (`summary.validate`) — 금지어·80자·입력에 있는 티커만. 걸린 항목만 버린다.
- **`stop_reason == "refusal"`을 먼저 본다** — Opus 5는 거부 응답을 HTTP 200으로 준다. content를 읽기 전에 확인.
- **DART `013`은 오류가 아니다** — "조회된 데이터가 없습니다" = 공시 0건. `020`은 한도 초과.
- **DART 제목은 흔들린다** — `유상증자결정` / `유상증자 결정` / `[정정]유상증자결정` / `ㆍ`. `flags.normalize()`를 거치지 않은 매칭은 미탐.
- **`ksa_signals.sent_email`은 항상 false다** — 상위가 저장하지 않는다. 메일 집합은 `suppressed = false` (SPEC F2, 2026-08-26 실측).
- **게이트는 이벤트가 아니라 DB를 믿는다** — dispatch는 "워크플로가 끝났다"만 말한다. `ksa_runs` 오늘 행이 없으면 1분×10회 기다렸다 `gate_timeout`.
- **체크포인터를 쓰지 않는다** — 단발 배치. 상태에 API 키가 섞이면 디스크에 남는다.
- **그래프를 고쳤으면 `scripts/export_graph.py`를 다시 돌린다** — `docs/GRAPH.md`가 낡으면 문서가 거짓말을 한다. 설계도는 `docs/graph.png`.
- **티커는 숫자가 아니다** — `0126Z0`. `corpCode.xml`의 `stock_code`도 문자열로 비교.
- **`create table if not exists`는 마이그레이션이 아니다.**
- **pip은 이 디렉토리에서** — 워크스페이스 루트 오설치 사례 있음.
- **`ksa_*`·`ksc_*`에 쓰지 않는다** — 상위 프로젝트 소유다.

## 선행 프로젝트

| 프로젝트 | 관계 |
|----------|------|
| `../krx-signal-alerts/` | **데이터 공급자.** 읽기만 한다. 3층 분리·발송 방식·조심할 것 목록을 그대로 계승. 코드는 가져오지 않고 다시 쓴다 |
| `../idea_md/stock-mcp-ideas.md` | 출발점 문서. §2-2(SPEC)에 무엇이 달라졌는지 기록 |

## 진행 상태

**M0 진행 중** (2026-08-26). 진도는 `docs/TASKS.md` 대시보드 참조.
