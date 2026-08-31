# krx-signal-briefing

> 🇺🇸 English: [README.md](README.md)

**차트 신호에 근거가 있는지 확인해 주는 두 번째 아침 메일.**

[krx-signal-alerts](https://github.com/daehyub71/krx-signal-alerts)는 평일 08:20 KST에 전 종목을 다섯 가지
기술적 전략으로 훑어 걸린 종목을 메일로 보낸다. 그 메일은 **"차트 조건이 맞았다"**까지만 말한다.
지난주 전환사채를 찍은 종목의 돌파인지, 아무것도 없는 깨끗한 돌파인지는 구분해 주지 못한다.

이 프로젝트는 그다음 질문 — **근거가 있는가, 그리고 차트와 같은 말을 하는가** — 에 답한다.
신호가 난 종목마다 서로 다른 세 갈래를 모아 맞춰 본다.

```
차트 신호 (상위)   "MTF 정배열 전환" · "VCP 수축"
      │
      ├─ 1  DART 공시    무슨 일이 있었나 — CB 120억, 잠재 물량 18.63%, 시가하락 시 조정 조항
      ├─ 2  네이버 뉴스   왜 그랬나 — "전액 제2공장 시설투자"
      └─ 3  기관·외국인   누가 사고 팔았나 — 30일 순매수 흐름
      │
      ▼
  정합 / 불일치 / 무관   + 근거 서술 + 규칙 점수 (한계 표기 포함)
```

**판정과 점수는 코드가 낸다. 모델이 아니다.** `verdict.judge()`는 순수 함수이고, Claude는 건네받은
판정을 **설명**할 뿐이다. 모델에게 숫자를 물으면 지어낸다 — 2026-08-30에 실제로 겪었고,
고친 방법은 **묻지 않는 것**이었다.

> **진행 상태** — M0~M3·M6 완료, M4(자동화) 85%. 테스트 554개, ruff·mypy strict 통과.
> 깃허브 Actions에서 끝까지 돈다: 게이트 → 신호 44건 → 근거 서술 34건 → 벨셀 페이지 → 메일.
> 남은 것은 연속 5거래일 관찰.

## 종목 한 블록이 이렇게 나온다

2026-08-26 실제 출력, 메일의 평문 부분:

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

VCP 돌파 밑에 전환사채 공시 넉 장이 깔려 있고, 잠재 물량이 유통주식의 4분의 1이며 시가하락 시 조정
조항까지 붙어 있다. **판정: 불일치 26점.** `18.63%`와 `1,519원`은 공시 **본문**에서 읽어 낸 값이다 —
어느 공시 제목에도 나오지 않는다.

사실만 적고, 공시마다 DART 원문을 걸고, 매매 표현은 쓰지 않는다. 아무것도 안 걸린 종목은
**"최근 30일 공시 중 확인된 위험 유형 없음"**이라고 적는다 — **"리스크 없음"**이 아니다.

## 무엇으로 판정하나

| 층 | 하는 일 |
|---|---|
| **공시** (F5·F15·F16) | 키워드 규칙표가 공시를 🔴/🟡로 등급 매긴다. 반기보고서·IR개최 같은 **정형 공시는 접는다** — 처음 받아 보니 소음의 65%가 그것이었다. 걸린 공시는 **본문**까지 읽어 잠재 물량·자금 용도·표면이자율·조정 조항을 꺼낸다. |
| **뉴스** (F11 v2) | 검색어는 종목명만, 정렬은 관련도순, 그리고 **앞 글자가 한글이면 버리는** 제목 필터 — 그러지 않으면 `아이텍`이 `위세아이텍` 안에서 잡힌다. 실수집 적합도가 64% → 100%가 됐다. |
| **수급** (F17) | 기관·외국인·개인 30일 순매수를 상위 DB에서 **SQL 한 번**으로 읽는다. 새 API도 새 키도 없다. |
| **판정** (F18) | `verdict.judge()` — 순수 함수. 위험 등급·오버행 상한·조정 조항·이상 점수·수급 방향에 가중치를 준다. 결과에 **보지 않는 것**을 함께 적는다: 실적·밸류에이션, 업황, 시장 전체 흐름, 공시 이후의 주가. |
| **근거 서술** (F19) | 하루 1회 Claude Opus 5 일괄 호출, 종목당 2,000자 이내. 금지어·입력에 있는 티커·**우리가 세어 준 위험 건수**를 코드가 다시 대조해, 걸린 항목만 버린다. |

## 구조

![시스템 개요](docs/arch-overview.png)

- 상위 테이블(`ksa_signals`·`ksa_runs`·`ksc_*`)의 **읽기 전용 소비자**다. 쓰는 곳은 `ksb_*`뿐이고,
  그 테이블에는 **RLS 정책이 아예 없다** — service_role만 접근한다.
- 배치와 외부 API 사이에 **남이 만든 MCP 서버 2종**(`npx` stdio, 버전 고정)이 있다:
  [korean-dart-mcp](https://github.com/chrisryugj/korean-dart-mcp) ·
  [naver-search-mcp](https://github.com/isnow890/naver-search-mcp). 이들은 **데이터 소스이지 에이전트가
  아니다** — 도구 호출 순서는 파이썬 코드가 정하고 LLM에게 도구를 쥐어 주지 않는다. korean-dart-mcp가
  응답하지 않으면 OpenDART REST로 직접 폴백하고, 나머지 층은 없으면 없는 대로 메일에 표시한다.
- 상위 `alert.yml`의 마지막 단계가 **`repository_dispatch`로 깨운다** — HTTP 204에서 워크플로 시작까지
  20초로 실측됐다. 예비 cron(09:05 KST)이 놓친 dispatch를 받고, 그날 이미 돌았으면 아무것도 하지 않는다.
- **메일은 간략하게, 전문은 벨셀 페이지로** 유도한다. 그 페이지는 벨셀 SSO 보호를 **켠 채로** 두어
  본인만 볼 수 있고, 매 화면에 투자 권고가 아니라 참고용 테스트임을 밝힌다.

![LangGraph 그래프](docs/graph.png)

3층 분리는 상위 프로젝트 규칙 그대로다. 그래프 층(`state`·`nodes`·`graph`)만 LangGraph를 알고 노드는
20줄을 넘지 않는다. 도메인 층(`flags`·`routine`·`verdict`·`analysis`·`render`·`page`·`corp`)은 순수
함수이며 TDD 대상이다. I/O 층(`enrich`·`dart`·`dart_mcp`·`news_mcp`·`mcpc`·`llm`·`store`·`notify`·
`deploy`·`config`)만 부수효과를 알고, **예외를 밖으로 내지 않는다** — 여기서 예외가 새면 `record_run`에
못 가 그날의 실패 기록까지 사라진다.

![모듈 의존](docs/modules.png)

## 기술 스택

Python 3.11 + Node 20.19 · LangGraph · **MCP 파이썬 SDK**(stdio 클라이언트) · korean-dart-mcp / naver-search-mcp ·
Anthropic SDK(`claude-opus-5`, 하루 1회 일괄 스트리밍 호출) · 폴백용 OpenDART REST ·
Supabase(psycopg + supabase-py) · Gmail SMTP · Vercel Deployments API · 깃허브 Actions · pytest / ruff / mypy(strict)

## 설치

```bash
cd krx-signal-briefing
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env           # DART · Anthropic · 네이버 · Supabase · Gmail · Vercel
node --version                 # 20.19+ — MCP 서버는 npx로 뜬다
python scripts/apply_schema.py # ksb_* 테이블 생성 (멱등)
```

## 실행

```bash
python -m briefing.main --dry-run            # 저장·발송 없이 결과만
python -m briefing.main --date 20260828      # 특정 기준일 재현
python -m briefing.main --force              # 오늘 브리핑이 있어도 다시 만든다
python -m briefing.main --if-not-briefed     # 예비 cron용 — 이미 돌았으면 no-op
python scripts/dryrun.py --days 60           # 과거 신호 등급 분포 (발송·LLM 없음)
python scripts/export_graph.py               # 그래프를 고쳤으면 docs/GRAPH.md 재생성
```

## 검증

```bash
ruff check . && mypy && pytest -q
```

## 문서

| 파일 | 내용 |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | 요구사항(F/N/R ID), 결정 D1~D24, 데이터 모델, 문구 규칙 |
| [docs/PLAN.md](docs/PLAN.md) | 아키텍처, 그래프 설계, 마일스톤, 테스트 전략 |
| [docs/DESIGN.md](docs/DESIGN.md) | 메일·페이지 레이아웃 — 만들기 전에 수신자와 합의한 기록 |
| [docs/TASKS.md](docs/TASKS.md) | 진도율 대시보드, 태스크 체크리스트, 트러블슈팅 기록 |
| [docs/GRAPH.md](docs/GRAPH.md) | 컴파일된 그래프에서 자동 생성한 mermaid |
| [docs/TOKENS.md](docs/TOKENS.md) | 토큰 발급·교체 절차 |

## 경계

- **투자 권고가 아니다.** 공시·보도·수급이 무엇이었는지, 그것이 차트와 같은 말을 하는지까지만 적는다.
  추천도 등급도 예측도 하지 않는다. 금지어는 렌더러, LLM 프롬프트, LLM 출력을 검증하는 코드 **세 곳**에
  박아 두었고 — 걸린 서술은 다듬지 않고 **버린다**.
- **수신자는 한 사람.** 해석이 섞인 내용을 남에게 배포하면 유사투자자문업 경계를 건드린다.
  그래서 `RECIPIENTS`는 본인 하나이고 전문 페이지도 SSO 뒤에 둔다.
- 점수는 **일부러 부분적**이고 그렇다고 적는다: 실적·밸류에이션, 업황, 시장 전체 흐름,
  공시 이후의 주가를 보지 않는다.
- 최근 30일 안의 공시만 본다.

## 라이선스

MIT
