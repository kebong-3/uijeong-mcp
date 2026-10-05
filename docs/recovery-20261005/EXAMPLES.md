# 실제 업무 예시 — 1차 응답 확보, 후속 최종판 PENDING

아래 네 호출은 처음 제안한 재현 입력이며 `4.1.4-public.4`의 실제 공개 schema와 대조했다. 1차 `4.1.5-public.1` 검증에서는 더 작은 문서·표시 한도를 사용하는 입력 inventory로 네 도구의 실제 응답을 받았다. **제안 입력과 실제 실행 입력을 구분한다.** 실행한 값은 아래 원시 파일의 `call.arguments`에 있으며, 후속 `4.1.5-public.2`의 최종 실제 예시는 아직 PENDING이다. 최초 제안 입력은 [example-calls.json](example-calls.json)에 보존한다.

지역은 명시적으로 수원시를 지정한다. 기존 확인자료가 있는 동일 시나리오를 우선 재검증하는 것이며, 이 네 사례만으로 전국 일반화 성능을 주장하지 않는다.

## 1차 실제 결과의 핵심

| 분야 | 실제 1차 결과 | 확인된 범위·한계 | 원시 근거 |
|---|---|---|---|
| 부서 의회대응 | `PARTIAL`. 회의록 1개·발언 후보 7개를 검토했고 해당 부서로 분류된 답변은 0건 | 상류 `건축과` 검색 1,260건 중 1개만 읽었고 다음 offset=1. 부서 전체 질의가 없다는 의미가 아님. 실제 답변을 보여주는 양성 예시는 후속 추가조회 예정 | [council_department_brief](evidence/after-r1/calls/council_department_brief.json) |
| 사업예산 | `빌라가꿈관리소` 원명은 0건, 추가어 `소규모 공동주택`으로 수원 관련 사업 3개 발견 | 실제 기준일 2026-10-04, 일반회계. 후보는 안전점검 지원·노후 공동주택 유지관리·소규모 공동주택 활성화. 단위 및 같은 사업 관계는 미확인 | [council_finance_context](evidence/after-r1/calls/council_finance_context.json) |
| 조례 | `제5조의2(공동 관리소 설치 등)`을 원문과 같은 label/key로 반환 | 청소·안전 등 주거환경 개선을 위한 공동 관리소 설치·운영 규정 확인. 지정 판본 시행일 2025-12-31; 조회 기준일의 최신 판본은 별도 확인 필요 | [ordinance_get_document](evidence/after-r1/calls/ordinance_get_document.json) |
| 통합검토 | 법규·재정 각각 후보 3개, 대표 상태 `PARTIAL`, `candidate_status=CANDIDATES_FOUND` | 초기 `EMPTY`와 후속 발견을 구분. 재정 후보의 일반회계·20261004·기관코드 보존. 의원자료·정책배경 `SKIPPED`. 동일사업·법적 승인·제출완료를 확정하지 않음 | [council_context_pack](evidence/after-r1/calls/council_context_pack.json) |

예산 예시에서 `소규모 공동주택 활성화` 사업코드는 `37400002025302B6`이다. API가 현액 원시값 `627780000`, 지출 원시값 `443022560`을 반환했지만 `amount_unit=SOURCE_CONFIRMATION_REQUIRED`이므로 원 단위 금액으로 환산하지 않았다. 이 사업 전체를 빌라가꿈관리소의 확정 예산으로 귀속하지도 않았다.

1차 최소입력의 실제 자료와 별개로, 아래 제안 입력에 대응한 최종 출력란은 후속 검증 때 채운다.

## 1. 부서 의회대응

사용자 질문: “수원시 건축과가 2025년부터 2026년 10월 5일까지 의회에서 받은 주요 질의와 답변, 회기 전 확인사항을 정리해 주세요.”

```json
{
  "tool": "council_department_brief",
  "arguments": {
    "department": "건축과",
    "council": "수원시의회",
    "date_from": "2025-01-01",
    "date_to": "2026-10-05",
    "max_docs": 2,
    "source": "clik",
    "limit": 3
  }
}
```

출력에 기록할 내용: 회의일·회기·위원회, 질의 취지, 실제 답변자·답변 내용, 정식보고 여부, 추가 확인사항, DOCID·발언 위치, 실제 조회범위. `max_docs=2`이므로 기간 전체의 전수조사가 아니다. 답변 미연결을 실제 미답변 또는 미이행으로 단정하지 않는다.

**실제 상태 / 주요 결과 / 원문 위치 / receipt: PENDING**

## 2. 사업예산

사용자 질문: “수원시 소규모 공동주택 활성화 사업의 2026년 예산현액과 집행자료를 확인해 주세요. 기준일과 회계·단위도 같이 알려 주세요.”

```json
{
  "tool": "council_finance_context",
  "arguments": {
    "topic": "소규모 공동주택 활성화",
    "council": "수원시",
    "fiscal_year": 2026,
    "snapshot_date": "2026-10-05",
    "budget_stage": "current",
    "limit": 3
  }
}
```

출력에 기록할 내용: 정식 사업명·사업코드, 회계, 요청 기준일·실제 제공일, 현액·집행 원시값, 금액 단위와 그 확인근거, 반환 예산단계, 관련 정책과의 관계 확인 수준. 최신 자료 제공일로 보정되면 실제 날짜를 표시한다. 단위가 미확인인 숫자를 원 단위로 환산하거나 현액을 본예산으로 옮겨 쓰지 않는다.

**실제 상태 / 주요 결과 / 출처 / receipt: PENDING**

새 공개 인자 전달을 따로 확인할 때는 배포본 `tools/list`에 `search_terms`가 있는지 확인한 뒤 위 입력의 `topic`을 `빌라가꿈관리소`로 바꾸고 `search_terms: ["소규모 공동주택 활성화"]`를 추가한다. 이 추가 호출은 REC-01 검증이며 네 분야 예시의 기본 호출과 구분한다.

여러 추가 검색어를 사용하면 총 표현 한도에 의해 일부가 제외될 수 있다. 응답의 요청·계획·시도·제외 용어와 coverage를 확인하고, 미검색 표현을 검색 0건으로 정리하지 않는다(REC-08).

## 3. 조례 검토

사용자 질문: “수원시 소규모 공동주택관리 지원 조례의 공동 관리소 설치 근거 조문을 읽고, 원문 조번호와 시행·버전 확인 수준을 보여 주세요.”

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
    "offset": 0,
    "limit": 3,
    "max_chars": 2000
  }
}
```

ID/MST는 이전 실제 공식 API 반환 식별자다. 같은 판본의 원문을 재검증하는 입력으로 사용하며, 이 호출만으로 2026-10-05 현재의 최신 판본이라고 확정하지 않는다. 원천에서 문서가 바뀌거나 조회되지 않으면 공식 검색으로 반환된 새 식별자를 사용하고 변경 사유를 기록한다.

출력에 기록할 내용: 실제 법규명·관할·문서 ID/MST, `제5조의2`의 원문과 label/key 일치, 시행일·판본 확인 수준, 원문 URL·hash, 사업 적용 시 추가 확인사항.

통합 법규 검색에서 여러 지역의 조례가 나오면 각 행의 관할을 따로 대조한다. 다른 지역의 조례는 비교 후보로 표시한다. 검색 한도로 다음 페이지가 남으면 `PARTIAL`과 복구 절차를 보존하며, 공개 검색으로 전환할 때 페이지 크기가 다르면 1페이지부터 다시 시작한다.

**실제 상태 / 조문 요지 / 판본 확인 수준 / receipt: PENDING**

## 4. 의회·예산·조례 통합검토

사용자 질문: “수원시 빌라가꿈관리소에 대해 2025년부터의 의회 논의, 2026년 재정자료, 관련 조례를 함께 확인하고 같은 사업으로 연결된 부분과 추가 확인할 부분을 정리해 주세요.”

```json
{
  "tool": "council_context_pack",
  "arguments": {
    "topic": "빌라가꿈관리소",
    "council": "수원시의회",
    "date_from": "2025-01-01",
    "date_to": "2026-10-05",
    "fiscal_year": 2026,
    "max_docs": 2,
    "include_legal": true,
    "include_finance": true,
    "include_public_data": false
  }
}
```

출력 순서: 확인된 결론 → 조례 근거 → 예산 단계·기준별 표 → 의회 질의·답변과 정식보고 → 자료 간 관계·충돌 → 미확인 사항 → 조회범위·실행상태.

후속 검색에서 확보한 후보가 대표 요약에서 `EMPTY`로 가려지지 않는지, 회계·실제 기준일·단위·식별자·원문 위치가 축약 뒤에도 남는지 확인한다. 후보 발견과 같은 사업·상하위사업·법규 적용의 입증을 구분한다. 요청하지 않은 의원자료·정책배경의 실행 여부도 trace에서 확인한다.

**실제 상태 / 발견한 근거 / 관계 확인 수준 / 남은 확인사항 / receipt: PENDING**

## 실행 후 기록 양식

| 예시 | 실행시각 KST | 서버 버전 / commit | 상태·반환범위 | 실제 결과 파일 | request_id |
|---|---|---|---|---|---|
| 부서 의회대응 (1차) | 2026-10-05 22:56:25 | 4.1.5-public.1 / de2e6f5 | PARTIAL, 1개 문서에서 부서 답변 0건 | [원시 응답](evidence/after-r1/calls/council_department_brief.json) | `e74e50e2dc7c4660854b` |
| 사업예산 (1차) | 2026-10-05 22:56:41 | 4.1.5-public.1 / de2e6f5 | COMPLETE, 관련 사업 3개; 단위·동일사업 미확인 | [원시 응답](evidence/after-r1/calls/council_finance_context.json) | `ec4b8eb0e46843e6ae3b` |
| 조례 검토 (1차) | 2026-10-05 22:56:46경 원문 수집 | 4.1.5-public.1 / de2e6f5 | retrieved, 해당 조문 1개 | [원시 응답](evidence/after-r1/calls/ordinance_get_document.json) | `dd850cafd2c14663adf7` |
| 통합검토 (1차) | 원시 요청순서·stage trace 참조 | 4.1.5-public.1 / de2e6f5 | PARTIAL, 법규·재정 후보 각 3개 | [원시 응답](evidence/after-r1/calls/council_context_pack.json) | 출력에 receipt 미포함; trace 보존 |

후속 최종 버전의 4분야 결과와 양성 부서 예시는 PENDING이다.

원시 응답은 근거이고 사용자 예시는 읽기 쉬운 실제 결과 요약이다. 결과 JSON을 임의 길이에서 잘라 문서가 끊기게 만들지 않는다. 오류·부분완료·미확인 상태가 있으면 해당 예시 안에 함께 기록한다.
