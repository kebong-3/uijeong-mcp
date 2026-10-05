# 통합 MCP 실제 업무 예시

아래 결과는 **`4.1.5-public.2`의 실제 응답**이다. 사용한 입력은 [example-calls.json](example-calls.json), 전체 원시 응답은 각 절의 근거 파일에 있다. 수원 사례는 정의한 시나리오의 확인 결과이며 전국 모든 사업의 완전성을 의미하지 않는다.

예시는 실제 서버의 새 schema로 실행했다. 현재 대화에 로드된 연결의 인자 메타데이터는 이전 명세로 관측되었으며 Refresh는 수행하지 않았다. 같은 인자가 호스트에 보이지 않는 경우의 확인 범위와 조건별 안내는 [인수인계](HANDOFF.md#현재-대화의-연결-메타데이터)에 있다.

## 1. 부서 의회대응: 실제 질문과 답변

처음에는 `건축과`, 2025-01-01~2026-10-05, `max_docs=6`으로 조회했다. 최신 6개 원문에서 검토한 발언 후보 25개 중 부서 답변으로 분류된 것은 0개였다. 이 결과는 기간 전체의 질의 부재가 아니며 [처음 조회](evidence/after-r2/department-example.json)를 그대로 보존했다.

같은 운영 검증에서 실제 회의록을 읽어 **2026-07-15·도시미래위원회**라는 메타데이터를 확인한 뒤 해당 회의를 지정했다.

```json
{
  "tool": "council_department_brief",
  "arguments": {
    "department": "건축과",
    "council": "수원시",
    "date_from": "2026-07-15",
    "date_to": "2026-07-15",
    "committee": "도시미래위원회",
    "max_docs": 2,
    "limit": 3,
    "source": "clik"
  }
}
```

| 항목 | 실제 확인 |
|---|---|
| 회의 | 수원시의회 제403회 도시미래위원회, 2026-07-15 |
| 의원 질의 | 김은수 위원이 빌라가꿈관리소 확대 추진과 관련해 시에서 관리소장을 선발해 운영하는 방식인지 질문 |
| 집행부 답변 | 건축과장 이순헌은 관리자가 없는 소규모 빌라 구역을 정해 관리소장을 선발하고, 쓰레기 수거 후 잔재물 정리와 공용시설물 파손 수리 등을 맡기는 취지라고 설명 |
| 원문 위치 | DOCID `CLIKC2479358086714915`, 질의 turn 269 → 답변 turn 270 |
| 확인 상태 | `PARTIAL`, 공식 API 본문 열람. 개별 회의록 웹 URL은 미제공 |
| 다음 확인사항 | 채용·관리 구역·실제 업무범위·성과·예산 편성명세는 해당 후속 원문과 사업자료로 대조 |

근거는 [지정 회의의 실제 부서 조회](evidence/after-r2/department-located-meeting.json)의 `answered_items[1]`이다. 첫 항목 267→268은 질의 예고와 직함 소개이므로 실질 질문 예시로 사용하지 않았다.

이번 호출은 목록 14개를 검토해 원문 2개를 읽었고, 부서 답변으로 분류된 **발언 후보 80개 중 3개를 표시**했다. 80을 독립 질문 80건이나 공식 감사 지적 80건으로 해석하지 않는다. 요청한 날짜·위원회를 벗어난 기간 전수조사도 아니다. request_id는 `04686bf33e6a42a6aa2e`, 반환시각은 2026-10-05 23:20:18 KST다.

## 2. 사업예산: 정책명에서 관련 재정사업 찾기

```json
{
  "tool": "council_finance_context",
  "arguments": {
    "topic": "빌라가꿈관리소",
    "council": "수원시",
    "fiscal_year": 2026,
    "snapshot_date": "20261005",
    "budget_stage": "current",
    "search_terms": ["소규모 공동주택"],
    "limit": 3
  }
}
```

원명 `빌라가꿈관리소`로는 0건이었지만 추가 표현 `소규모 공동주택`이 실제 후속 검색에 전달되어 수원 관련 사업 3개를 찾았다. 요청한 2026-10-05 자료는 제공되지 않아 **실제 기준일 2026-10-04**로 보정되었다. 반환 회계연도는 2026, 회계는 모두 일반회계다.

**아래 숫자는 API 원시값이다.** 원천 단위가 `SOURCE_CONFIRMATION_REQUIRED`이므로 원·천원 금액으로 환산하지 않았고, 빌라가꿈관리소와 같은 사업인지도 확정하지 않았다.

| 관련 사업 후보 | 사업코드 | 예산현액 원시값 | 지출 원시값 |
|---|---|---:|---:|
| 소규모 공동주택 안전점검 지원(도비) | `37400002016300FF` | 73,000,000 | 0 |
| 노후 소규모 공동주택 유지관리(도비) | `3740000202230134` | 200,000,000 | 0 |
| 소규모 공동주택 활성화 | `37400002025302B6` | 627,780,000 | 443,022,560 |

`requested_stage_verified=true`는 요청한 현액 단계의 자료를 반환했다는 뜻이다. `amount_verified=false`, `same_project_verified=false`도 함께 남아 있다. 이를 확정 본예산·추경액으로 바꾸거나 관련 사업 전체를 특정 정책의 예산으로 귀속하면 안 된다.

[실제 재정 응답](evidence/after-r2/calls/council_finance_context.json)에 원시값·재원·회계·기관코드·실제 조회일·검색 시도가 모두 있다. 공식 링크는 [지방재정365 데이터셋](https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=0GAR4HBB8LWEBSL4NIHZ817053) 안내이며 개별 사업예산서 원문 링크가 아니다. request_id는 `54049eae06004a90b8ca`, 반환시각은 2026-10-05 23:18:32 KST다.

추가 검색어를 여러 개 넣으면 원명·표기 변형을 포함한 총 4개 표현 한도가 적용된다. 실제 검색하지 않은 용어는 `omitted_search_terms`·`unattempted_queries`·coverage로 확인한다.

## 3. 조례: 원문 조번호와 판본 확인

실제 `ordinance_search`가 반환한 문서 ID/MST를 사용했다.

```json
{
  "tool": "ordinance_get_document",
  "arguments": {
    "reference": {
      "kind": "ordinance",
      "document_id": "2209592",
      "mst": "2102111",
      "title_hint": "수원시 소규모 공동주택관리 지원 조례"
    },
    "keyword": "공동 관리소",
    "section": "articles",
    "limit": 1,
    "max_chars": 2000
  }
}
```

| 항목 | 실제 반환 |
|---|---|
| 법규·관할 | 수원시 소규모 공동주택관리 지원 조례 / 경기도 수원시 |
| 조문 | `제5조의2(공동 관리소 설치 등)` |
| 구조화 값 | label=`제5조의2`, key=`main:제5조의2`; 원문 표제와 일치 |
| 규정 요지 | 소규모 공동주택의 청소·안전 등 주거환경 개선을 위한 공동 관리소 설치·운영 |
| 문서 / 판본 | ID `2209592` / MST `2102111` |
| 해당 판본 공포·시행일 | 2025-12-31 |
| 내용 hash | `87998bc47f96736101a3b22cda562ac858711ec9e3d06aae68a4f2788458a210` |
| 열람 범위 | 해당 검색조건의 조문 1개. 별표 본문은 미수집 |
| 현행성 | `version_current_verified=false`; 시행일이 과거라는 이유만으로 최신 판본이라고 확정하지 않음 |

[실제 조례 응답](evidence/after-r2/calls/ordinance_get_document.json)과 [공식 판본 링크](https://www.law.go.kr/ordinInfoP.do?ordinSeq=2102111)를 대조할 수 있다. request_id는 `5a04fd7147c8419c8756`이다. 조문 조회 성공과 특정 사업에 대한 최종 법적 적용·지출 승인 판단은 구분한다.

## 4. 통합검토: 후보 발견과 관계 확인을 함께 제시

```json
{
  "tool": "council_context_pack",
  "arguments": {
    "topic": "빌라가꿈관리소",
    "council": "수원시",
    "date_from": "2025-01-01",
    "date_to": "2026-10-05",
    "fiscal_year": 2026,
    "max_docs": 1,
    "include_legal": true,
    "include_finance": true,
    "include_public_data": false,
    "include_member_records": false,
    "include_policy_background": false
  }
}
```

| 분야 | 실제 결과 | 확인 수준 |
|---|---|---|
| 의회 | 제한된 원문 범위에서 발언 후보 6개 | `PARTIAL`, 전체 기간 전수조사 아님 |
| 조례 | 소규모 공동주택관리 지원 조례·건축기본 조례·도시계획 조례 후보 3개 | 최초 `EMPTY`와 후속 `PARTIAL`/`CANDIDATES_FOUND`를 구분. 적용성 미확인 |
| 재정 | 앞 예산 예시의 관련 사업 후보 3개 | 일반회계·20261004·기관코드·사업코드 보존. 단위·동일사업 미확인 |
| 부가조회 | 의원자료·정책배경 모두 `SKIPPED` | 명시적으로 요청한 근거 탐색에 집중 |
| 제출 가능 여부 | `ready_for_submission=false` | 후보 발견만으로 공식 검토 완료·법적 승인으로 바꾸지 않음 |

**확인된 결론:** 공식 회의록의 대상 표현을 이용해 관련 조례와 재정사업 후보를 찾아 연결했다. 최초 명칭 검색이 0건이어도 후속 후보 발견이 결과에서 사라지지 않는다.

**추가 대조할 사항:** 빌라가꿈관리소와 정식 재정사업의 동일·상하위 관계, 업무보고액과 의결 본예산·추경액의 관계, 원천 금액 단위, 조례 최신 판본·적용대상·지출근거다. 이 부분은 근거를 확보하기 전까지 미확인으로 남겼다.

전체 근거는 [실제 통합 응답](evidence/after-r2/calls/council_context_pack.json)에 있다. 응답에는 실행 단계별 trace가 있으며 최상위 request_id receipt는 포함되지 않았다. 없는 receipt를 만들어 적지 않았다.

## 4분야 입력과 결과의 추적

| 분야 | 결과 파일 | request_id / 추적 방법 |
|---|---|---|
| 부서 의회대응 | [지정 회의 부서 조회](evidence/after-r2/department-located-meeting.json) | `04686bf33e6a42a6aa2e`; 원문 269→270 |
| 사업예산 | [재정 조회](evidence/after-r2/calls/council_finance_context.json) | `54049eae06004a90b8ca` |
| 조례 | [조례 원문](evidence/after-r2/calls/ordinance_get_document.json) | `5a04fd7147c8419c8756` |
| 통합 | [통합 근거](evidence/after-r2/calls/council_context_pack.json) | 실제 call 인자·원문 식별자·stage trace |

앞의 부서 양성 예시는 42회 최소입력 검증과 별도로 확인했다. 최소입력의 작은 범위에서 0건이었던 기록을 삭제하지 않았다. 원시 결과와 설명은 일치시키되, 반환 항목수·독립 질문수·공식 감사 지적수는 서로 바꾸어 쓰지 않는다.
