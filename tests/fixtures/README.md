# 테스트 표본

| 파일 | 출처 | 담은 케이스 |
|------|------|-------------|
| `corpcode_sample.xml` | OpenDART `corpCode.xml`(zip 안의 `CORPCODE.xml`) **형식을 본떠 손으로 작성** — 공식 가이드 필드 5개(`corp_code` · `corp_name` · `corp_eng_name` · `stock_code` · `modify_date`) | ① 정상 ② 값 앞뒤 공백·개행 ③ 문자 섞인 티커 `0126Z0` ④ 비상장 = 공백 한 칸 ⑤ 비상장 = 빈 태그 ⑥ `stock_code` 태그 없음 ⑦ 같은 `stock_code`에 `corp_code` 둘(최신 `modify_date` 우선) ⑧ 완전 동일 항목 중복 |
| `corpcode_error_800.xml` | **2026-08-29(토) 10:39 KST 실제 응답 원문** — 시스템 점검 중 `corpCode.xml`이 HTTP 200으로 돌려준 본문 | zip이 아니라 XML 오류 본문. `dart.py`는 `PK` 매직 바이트 또는 `<status>`로 구분해야 한다 |

✅ **실파일 대조 완료** (2026-08-29 10:55 KST, 점검 종료 직후): zip 3.6MB · `CORPCODE.xml` · 루트 `result` · 항목 `list` · 태그 5개 그대로 ·
118,804건 중 상장사 3,988 · **비상장은 전부 공백 한 칸 `' '`** · 상장 `stock_code`에 공백 섞임 0 · **중복 0** · `corp_code` 전부 8자리 · 문자 섞인 티커 58개(`0009K0` 등).
표본의 ⑦·⑧(중복)은 실파일에 없는 **방어용** 케이스다.

| 파일 | 출처 | 내용 |
|------|------|------|
| `report_names.txt` | `scripts/sample_reports.py` — 2026-08-29, 최근 90일 신호 종목 153개 × 120일 창, DART 153회 | 실제 `report_nm` 352종 · 공시 3,000건, 빈도순. **규칙표(SPEC F5) 확정 근거** |
| `list_sample.json` | 같은 스크립트 | `list.json` 항목 원문 12건 (`Disclosure.to_json()` 형태) |

표본을 다시 뽑을 때: `python scripts/sample_reports.py` (DART 호출 = 종목 수 + 1).
