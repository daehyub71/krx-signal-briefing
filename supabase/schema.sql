-- krx-signal-briefing 스키마 (SPEC §5)
--
-- 같은 Supabase 프로젝트에 krx-signal-alerts의 ksa_*, krx-stock-charts의 ksc_* 테이블이 있다.
-- 이 프로젝트가 소유하는 것은 ksb_* 둘뿐이고, ksa_*는 읽기만, ksc_*는 읽지도 않는다.
--
-- 적용: python scripts/apply_schema.py
-- 재실행해도 안전하다(멱등).

-- ─────────────────────────────────────────────
-- 브리핑 (F9)
-- 신호 한 건에 대한 공시 판정 결과. PK가 ksa_signals와 같아 1:1로 대응한다.
-- ─────────────────────────────────────────────
create table if not exists ksb_briefings (
  d            date not null,              -- 신호 기준일 (= ksa_signals.d)
  strategy     text not null,
  ticker       text not null,

  -- ksa_signals.name 스냅샷. 조인 없이 렌더하고, 사명이 바뀌어도 그날의 이름이 남는다.
  name         text not null default '',

  -- OpenDART 고유번호(8자리). null = corpCode.xml에 없음 (F3 'unknown')
  corp_code    text,

  -- 'red' | 'amber' | 'none' | 'unknown' | 'error'  (F5)
  -- 'none'은 "없다"가 아니라 "최근 30일 공시 중 확인된 위험 유형 없음"이다 (N1).
  level        text not null,

  -- 등급을 올린 공시만. 점수가 아니라 "어떤 공시 때문인지"를 남긴다 (D5).
  -- [{rule, level, report_nm, rcept_no}]
  flags        jsonb not null default '[]'::jsonb,

  -- 창 안의 공시 전체. 메일이 이걸 그대로 렌더한다.
  -- [{rcept_dt, report_nm, rcept_no, flr_nm, corrected}]
  disclosures  jsonb not null default '[]'::jsonb,

  window_days  integer not null default 30,

  -- F14 Claude 요약. null = 공시 0건이거나 생성 실패
  summary      text,

  -- 2·3단계 예약 (F11 뉴스 · F12 수급)
  news         jsonb,
  flow         jsonb,

  created_at   timestamptz not null default now(),

  primary key (d, strategy, ticker),

  constraint ksb_briefings_level
    check (level in ('red', 'amber', 'none', 'unknown', 'error')),

  -- 티커는 숫자가 아니다. 0126Z0처럼 문자가 섞인 6자리가 실재한다.
  constraint ksb_briefings_ticker_format check (ticker ~ '^[0-9A-Z]{6}$')
);

-- ksa_signals로의 외래키를 일부러 걸지 않는다 — 상위가 행을 지워도 이력은 남아야 한다.

-- ── 마이그레이션 ──────────────────────────────
-- `create table if not exists`는 **이미 있는 테이블에 열을 추가하지 않는다.**
-- 열을 늘릴 때는 반드시 여기에 `alter table ... add column if not exists` 한 줄을 더한다.

-- v2.0 (2026-08-29) F4b 보조 신호 — korean-dart-mcp
--   anomaly: disclosure_anomaly {score, verdict, summary, flags}  — 등급을 바꾸지 않는 참고값
--   insider: insider_signal {signal, buy/sell 건수, 인원, 순변동주식, summary} — 매도 군집이면 🟡 플래그
--   null = 그날 생략됨(서버 미기동·실패). '없음'이 아니라 '못 봄'이다.
alter table ksb_briefings add column if not exists anomaly jsonb;
alter table ksb_briefings add column if not exists insider jsonb;
-- 공시 본문 (F15, v3.0) — 플래그된 공시만. 오버행 비율·자금용도·전환가·미상환잔액이 여기 있다.
-- 제목 한 줄로는 같아 보이는 두 전환사채가 5.10%와 18.63%로 갈린다 (2026-08-26 실측).
alter table ksb_briefings add column if not exists bodies jsonb not null default '[]'::jsonb;
-- 기관·외국인 수급 30일 (F17, v3.0) — 상위 `ksc_investor_flows`에서 읽어 담는다.
-- 날짜 오름차순 배열. 생략됐으면 null (0건과 다르다).
alter table ksb_briefings add column if not exists flows jsonb;

-- 종목축 조회(드라이런·이력)용. PK는 (d, strategy, ticker) 순서라 종목축을 못 받는다.
create index if not exists ksb_briefings_by_ticker
  on ksb_briefings (ticker, d desc);

-- ─────────────────────────────────────────────
-- 실행 기록
-- "안 온 게 정상인지 고장인지"를 사후에 가리는 유일한 기록이다.
-- 실패한 실행도 반드시 남는다 — record_run이 finalize보다 앞에 있는 이유다.
-- 예비 cron(F0)은 그날 행이 있으면 no-op으로 끝난다 — 상태는 보지 않는다.
-- ─────────────────────────────────────────────
create table if not exists ksb_runs (
  run_at        timestamptz primary key default now(),
  data_date     date,                     -- 게이트가 읽은 상위 data_date. 게이트 실패 시 null
  signal_n      integer not null default 0,
  red_n         integer not null default 0,
  amber_n       integer not null default 0,
  error_n       integer not null default 0,  -- DART 조회 실패 종목 수
  dart_calls    integer not null default 0,  -- 일 한도(20,000) 대비 사용량
  summary_n     integer not null default 0,  -- F14 생성 성공 수. 0인데 공시 있는 종목이 있으면 LLM 실패
  llm_tokens    integer not null default 0,  -- 입력+출력 토큰 (비용 추적)
  status        text not null,

  -- 오류 코드·요약 실패 사유·종목별 조회 실패 등
  detail        jsonb not null default '{}'::jsonb,

  constraint ksb_runs_status
    check (status in ('ok', 'no_signals', 'gate_timeout', 'dart_partial', 'dart_failed', 'send_failed'))
);

create index if not exists ksb_runs_by_date on ksb_runs (data_date desc);

-- ─────────────────────────────────────────────
-- RLS — 읽기는 공개(뒤에 웹이 anon 키로 읽을 수 있게), 쓰기는 service_role만.
-- service_role은 RLS를 우회하므로 쓰기 정책을 따로 만들지 않는다.
-- 상위 anon 키 범위 이슈(SPEC R6)를 이 테이블로 넓히지 않는다.
-- ─────────────────────────────────────────────
alter table ksb_briefings enable row level security;
alter table ksb_runs      enable row level security;

drop policy if exists ksb_briefings_read on ksb_briefings;
drop policy if exists ksb_runs_read      on ksb_runs;

create policy ksb_briefings_read on ksb_briefings for select to anon, authenticated using (true);
create policy ksb_runs_read      on ksb_runs      for select to anon, authenticated using (true);
