# krx-signal-briefing

> 🇺🇸 English: [README.md](README.md)

**아침 신호 각 건에 최근 DART 공시 사실을 붙여 보내는 두 번째 메일.**

[krx-signal-alerts](https://github.com/daehyub71/krx-signal-alerts)는 국내 전 종목을 다섯 전략으로 스크리닝해
평일 08:20 KST에 메일로 보냅니다. 그 메일은 *"차트 조건이 맞다"*까지만 말합니다.
깨끗한 돌파인지, 지난주 전환사채 발행 결정 위에 올라탄 돌파인지는 구분하지 못합니다.

이 프로젝트가 그 빈틈을 채웁니다. 상위 워크플로가 끝나면 깨어나 같은 신호를 읽고,
**OpenDART**에서 종목별 최근 30일 공시를 가져와 투명한 키워드 규칙표로 등급(🔴 / 🟡)을 매기고,
**Claude Opus 5**에 한 줄 사실 요약을 시킨 뒤, 첫 메일과 1:1로 대응하는 두 번째 메일을 보냅니다.

> **상태: M0(뼈대) 진행 중** — SPEC v1.1 / PLAN v1.0 확정 2026-08-26. 아직 배포 전.

## 두 번째 메일의 모양

```
가비아 [079940] 46,000원 +1.32%
  ✓ 월봉 종가 > MA20 : …            ← 첫 메일의 조건 5줄 그대로
  ─────────────────────────────────────────────
  🔴 공시  최근 30일 4건 · 위험 유형 2건
           · 08/22 전환사채권발행결정          [원문]  ← 🔴
           · 08/11 최대주주변경                [원문]  ← 🔴
           · 08/05 분기보고서                  [원문]
  💬 08/22 CB 발행 결정, 08/11 최대주주 변경 — 최근 30일 위험 유형 2건
```

사실만 나열하고, 모든 공시에 DART 원문 링크를 달고, 매수·매도 표현은 쓰지 않습니다.
아무것도 걸리지 않은 종목은 *"최근 30일 공시 중 확인된 위험 유형 없음"*이지 *"리스크 없음"*이 아닙니다.

## 아키텍처

![시스템 개요](docs/arch-overview.png)

- 상위 테이블(`ksa_signals` · `ksa_runs`)의 **읽기 전용 소비자**. 같은 Supabase 프로젝트의 `ksb_*` 테이블에만 씁니다.
- 상위 `alert.yml` 마지막 단계의 **`repository_dispatch`**로 깨어나 신호 메일 뒤 수십 초 안에 시작합니다. 예비 cron(09:05 KST)은 dispatch가 오지 않은 날을 받쳐 주고, 이미 돌았으면 no-op입니다.
- **LangGraph** 상태 그래프 — DB 게이트(1분 × 10회 재시도), 종목별 `Send()` fan-out으로 DART 조회, 격리된 `summarize` 노드. LLM이 죽어도 경고 한 줄을 달고 메일은 나갑니다.

![LangGraph 그래프](docs/graph.png)

상위 프로젝트와 같은 3층 규칙 — 그래프 층만 LangGraph를 알고, 도메인 층(`corp` · `flags` · `render` · `summary`)은
순수 함수이자 TDD 대상이며, I/O 층(`dart` · `llm` · `store` · `notify`)만 부수효과를 가집니다.

![모듈 의존관계](docs/modules.png)

## 스택

Python 3.11 · LangGraph · Anthropic SDK(`claude-opus-5`, 하루 1회 일괄 호출) · OpenDART REST(`corpCode.xml` + `list.json`, 하루 약 16회) ·
Supabase(psycopg + supabase-py) · Gmail SMTP · 깃허브 Actions · pytest / ruff / mypy(strict)

## 설치

```bash
cd krx-signal-briefing
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env           # DART_API_KEY · ANTHROPIC_API_KEY · Supabase · Gmail 채우기
python scripts/apply_schema.py --verify   # ksb_* 테이블 생성 + anon 쓰기 차단 확인
```

## 실행

```bash
python -m briefing.main --dry-run            # 저장·발송 없이
python -m briefing.main --date 20260825      # 과거 날짜 재현
python -m briefing.main --force              # 오늘 브리핑이 있어도 다시 만든다
python -m briefing.main --if-not-briefed     # 예비 cron 모드 — 오늘 이미 돌았으면 no-op
```

## 검증

```bash
ruff check . && mypy && pytest -q
python scripts/export_graph.py               # 그래프를 고쳤으면 docs/GRAPH.md 재생성
```

## 문서

| 파일 | 내용 |
|---|---|
| [docs/SPEC.md](docs/SPEC.md) | 요구사항(F/N/R ID) · 결정 D1~D11 · 데이터 모델 · 문구 규칙 |
| [docs/PLAN.md](docs/PLAN.md) | 아키텍처 · 그래프 설계 · 마일스톤 M0~M5 · 테스트 전략 |
| [docs/TASKS.md](docs/TASKS.md) | 진도율 대시보드 · 태스크 체크리스트 · 트러블슈팅 기록 |
| [docs/GRAPH.md](docs/GRAPH.md) | 컴파일된 그래프의 mermaid (자동 생성) |

## 경계

- **투자 조언이 아닙니다.** 메일은 공시를 나열할 뿐 추천·평가·전망을 하지 않습니다.
- **수신자 1명.** 해석이 섞인 신호를 남에게 배포하면 유사투자자문업 규제 대상이 됩니다.
- 30일 창 안의 공시만 봅니다. 창 밖의 것, 보고서 본문 안의 것은 보지 못합니다.

## 라이선스

MIT
