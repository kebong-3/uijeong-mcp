# 새 기능 입력 예시

아래 숫자·자료명은 기능 설명용 합성자료입니다. 실제 서구 사업의 사실로 사용하지 않습니다. `E:...` 식별자는 실제 준비자료 결과에서 복사해야 하며 임의로 만들 수 없습니다.

## 1. 답변 준비

```json
{
  "topic": "천원국시",
  "department": "실제 작성부서명",
  "council": "광주 서구",
  "date_from": "2024-01-01",
  "date_to": "2026-09-20",
  "meeting_type": "행정사무감사",
  "source": "auto",
  "max_docs": 6,
  "max_events": 6
}
```

도구: `council_prepare_response`. `max_docs`는 출처별 상세 상한입니다. 기본 auto는 서구 홈페이지와 CLIK을 각각 조회할 수 있습니다. 키가 없거나 일부 출처가 실패하면 PARTIAL 또는 ERROR를 그대로 읽습니다.

같은 입력에 반환된 `snapshot_id`, `event_offset=next_event_offset`을 넣으면 저장된 공개 근거의 다음 페이지를 읽습니다. facts는 서버에 저장되지 않으므로 다음 요청에서 필요하면 다시 전달합니다. `next_actions`는 아직 수집하지 못한 출처 목록을 계속 읽는 별도 경로입니다.

## 2. 제공자료와 답변 문장 대조

도구: `council_audit_claims`.

```json
{
  "draft": "지원 인원은 100명입니다. 모든 문제가 해결되었습니다.",
  "as_of": "2026-09-20",
  "facts": [{
    "id": "F1", "text": "지원 인원은 100명입니다.",
    "document_ref": "합성 실적표 2쪽", "as_of": "2026-09-01",
    "unit": "명", "fiscal_year": 2026
  }],
  "claims": [{
    "text": "지원 인원은 100명입니다.",
    "kind": "current_statement", "citation_id": "F:F1",
    "support_excerpt": "지원 인원은 100명입니다.", "start_char": 0
  }]
}
```

첫 문장은 위치와 발췌를 대조합니다. 두 번째 문장은 근거 연결이 없는 구간으로 남습니다. 첫 문장의 숫자가 같아도 사실성과 의미가 입증됐다는 뜻은 아닙니다.

| kind | 용도 |
|---|---|
| direct_quote | 직접 인용. text와 support_excerpt가 그대로 일치해야 함 |
| historical_summary | 당시 발언의 요약. 문맥·의미는 담당자 확인 |
| current_statement | 현재 사실 주장. 과거 회의록만 연결하면 별도 경고 |

동일 문장이 초안에 여러 번 있으면 `start_char`를 지정합니다. Python 문자열 기준 0부터 시작합니다. 새 도구가 만든 `citation_id`는 원래 `snapshot_id`와 함께 사용해야 합니다. 스냅샷 만료·사용자 변경 시 재수집합니다.

## 3. 단위와 비교기준 확인

도구: `council_compare_metrics`.

```json
{
  "data": [{
    "name": "합성사업 예산", "mode": "year_over_year",
    "previous": {
      "value": "1", "unit": "억원", "fiscal_year": 2025,
      "metric": "사업비", "entity": "합성기관", "population": "사업 전체",
      "period_basis": "연간", "accounting_basis": "최종예산", "document_ref": "합성 2025 예산서"
    },
    "current": {
      "value": "120000", "unit": "천원", "fiscal_year": 2026,
      "metric": "사업비", "entity": "합성기관", "population": "사업 전체",
      "period_basis": "연간", "accounting_basis": "최종예산", "document_ref": "합성 2026 예산서"
    }
  }]
}
```

결과: 20000000원 증가, 20.00% 증가. 한쪽의 `accounting_basis`를 `본예산`으로 바꾸면 비교 검토가 필요하므로 `calculation=null`입니다. 80%→90%는 10%p로 표시합니다. 기준값이 0이면 증감률은 null입니다.

`period_basis`에는 연간/동일 월 누적 등의 집계 범위, `population`에는 대상·분모, `accounting_basis`에는 본예산/최종예산/실인원 등의 산정기준을 구체적으로 씁니다. 둘 다 단순히 “같음”이라고 쓰는 것으로 실제 비교 가능성이 입증되지는 않습니다.

## 4. 과거 발언 비교

도구: `council_compare_evidence`. 서로 다른 준비자료의 snapshot_id를 최대 4개까지 전달할 수 있습니다.

```json
{
  "snapshot_ids": ["실제 첫 번째 식별자", "실제 두 번째 식별자"],
  "pairs": [{
    "left": {"citation_id": "실제 E: 식별자", "excerpt": "첫 번째 발언의 정확한 원문"},
    "right": {"citation_id": "실제 다른 E: 식별자", "excerpt": "두 번째 발언의 정확한 원문"}
  }]
}
```

두 발언의 숫자·조건·부정 단서를 나란히 보여줍니다. 자동으로 “말을 바꿨다”, “동일 요구가 반복됐다”, “미이행이다”라고 판정하지 않습니다. 현재 자료·정책 변경·기준 차이를 함께 확인합니다.
