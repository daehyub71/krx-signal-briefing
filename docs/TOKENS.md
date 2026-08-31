# TOKENS.md — 토큰 발급·교체

이 프로젝트가 쓰는 **사람이 손으로 만들어야 하는 토큰 두 개**의 발급·교체 절차다.
나머지 자격증명(DART·Anthropic·네이버·Supabase·Gmail)은 각 서비스에서 한 번 받아
`.env`와 리포 Secrets에 넣으면 끝이고, 여기서는 다루지 않는다.

| 토큰 | 어디에 | 무엇을 위해 | 지금 상태 |
|------|--------|-------------|-----------|
| `VERCEL_TOKEN` | 이 리포 | 전문 페이지를 Vercel에 올린다 (F20) | **CLI 세션 토큰 — 교체 권장** |
| `BRIEFING_DISPATCH_TOKEN` | **상위** `krx-signal-alerts` | 알림이 끝나면 이 리포를 깨운다 (D3·F0) | **미발급** |

---

## 1. `VERCEL_TOKEN` — 대시보드 토큰으로 교체

### 왜 바꾸나

지금 들어 있는 값은 `vercel` CLI가 로그인할 때 만든 **세션 토큰**이다.
동작은 하지만 **`vercel logout`을 하거나 세션이 만료되면 무효**가 되고,
그러면 배포가 조용히 실패한다 (메일은 링크 없이 나간다 — 고장은 아니지만 링크가 사라진다).

### 발급

1. <https://vercel.com/account/tokens> 접속
2. **Create Token**
   - **Name**: `krx-signal-briefing` (어디에 쓰는지 알아볼 수 있게)
   - **Scope**: `daehyub71's projects`
   - **Expiration**: 원하는 기간. 무기한을 고르면 만료일 관리가 없어지는 대신,
     유출 시 스스로 닫히지 않는다
3. 만들면 **한 번만 보인다.** 그 자리에서 복사한다

### 교체

```bash
cd ~/youtube_src/krx-signal-briefing

# ① .env 의 VERCEL_TOKEN= 줄을 새 값으로 바꾼다 (편집기로)

# ② 리포 Secrets 갱신 — 값이 셸 히스토리에 남지 않게 표준입력으로 넣는다
printf %s '새-토큰' | gh secret set VERCEL_TOKEN
```

### 확인

```bash
source venv/bin/activate
python -m briefing.main --date 20260827 --force | grep publish
# [publish] 전문 페이지 https://krx-signal-briefing-….vercel.app/20260826.html
```

`전문 페이지 생략: …` 이 나오면 토큰이 안 먹은 것이다.
**그래도 메일은 간다** — 링크만 빠진다 (F20).

### 배포 보호는 켠 채 둔다

새 Vercel 프로젝트는 **SSO 보호**가 기본으로 켜져 있고, 그대로 둔다 (R7 v3.1).
익명 접근은 Vercel 인증 화면에서 막히고 분석 내용이 보이지 않는다 —
판정과 점수가 남에게 가지 않게 하는 가장 확실한 장치다.
끄면 URL을 아는 누구나 열 수 있고, 그 순간 유사투자자문업 경계를 건드린다.

---

## 2. `BRIEFING_DISPATCH_TOKEN` — 상위가 이 리포를 깨우는 토큰

### 왜 필요한가

`workflow_run`은 **같은 저장소 안에서만** 동작한다.
상위 `krx-signal-alerts`가 다른 리포인 이 프로젝트를 깨우려면 `repository_dispatch`뿐이고,
그러려면 **이 리포에 쓸 수 있는 토큰**이 상위 리포의 Secrets에 있어야 한다.

없어도 브리핑은 나간다 — 예비 cron(09:05 KST)이 돈다. 다만 **45분 늦는다.**

### 발급 — fine-grained PAT

1. <https://github.com/settings/personal-access-tokens/new>
2. 위쪽을 아래대로 채운다

   | 항목 | 값 |
   |------|-----|
   | Token name | `briefing-dispatch` |
   | Resource owner | `daehyub71` |
   | Expiration | 1년 권장. 무기한도 되지만 유출돼도 스스로 닫히지 않는다 (아래 참고) |
   | Repository access | **Only select repositories** → `daehyub71/krx-signal-briefing` **하나만** |

3. **Permissions** — 화면이 2026년에 바뀌었다. 예전처럼 긴 드롭다운 목록이 아니라
   `Repositories 0 / Account 0` 탭과 **`+ Add permissions`** 버튼이 있는 빈 상태로 시작한다.

   1. **`+ Add permissions`** 클릭
   2. 검색창에 **`Contents`**
   3. **Contents** 선택 → 옆 드롭다운을 **`Read and write`**
   4. 추가되면 `Repositories 1`(`Metadata: Read-only`가 자동으로 붙어 `2`일 수도 있다)로 바뀐다
   5. **`Account` 탭은 손대지 않는다** — `0`인 채로 둔다

   `Contents: Read and write`가 `repository_dispatch`를 보내는 데 필요한 **유일한** 권한이다.
   **`Repositories 0`인 채로 만들면 dispatch가 403으로 실패한다.**

3. **Generate token** → 한 번만 보이니 그 자리에서 복사

### 상위 리포에 넣는다

```bash
cd ~/youtube_src/krx-signal-alerts
printf %s '새-토큰' | gh secret set BRIEFING_DISPATCH_TOKEN
```

### 확인

상위 워크플로를 수동 실행하고 마지막 단계를 본다:

```bash
cd ~/youtube_src/krx-signal-alerts
gh workflow run "alert"          # dry-run 이 아니어야 dispatch 가 나간다
gh run watch --exit-status
```

- `브리핑 깨움 (204)` → 성공. 이 리포에 `briefing` 워크플로가 곧 뜬다
- `BRIEFING_DISPATCH_TOKEN 없음 …` → Secrets 미등록
- `브리핑 깨우기 실패 HTTP 404` → 토큰이 이 리포에 접근 권한이 없다 (Repository access 확인)
- `… HTTP 403` → 권한이 모자란다 (Contents: Read and write 확인)

**어느 경우든 상위 워크플로는 실패하지 않는다** — 알림은 이미 나갔고,
브리핑은 예비 cron으로 돈다.

---

## 조심할 것

- **`.env`는 절대 커밋하지 않는다.** `.gitignore` 대상이며, 이 리포는 public이다
- 토큰을 셸에 그대로 치면 히스토리에 남는다 — 위처럼 `printf %s '…' | gh secret set …`을 쓴다
- `gh secret set`의 값은 로그에 마스킹되지만, **터미널 스크롤백에는 남는다**
- **만료일을 정했다면** `docs/TASKS.md` 「미해소 이슈」에 적어 둔다 — 지나면 **조용히** 안 돈다.
  무기한으로 만들었다면 적을 것은 없지만, 대신 이 토큰이 살아 있다는 사실을 잊기 쉽다 —
  쓰지 않게 되면 <https://github.com/settings/tokens?type=beta>에서 지운다
