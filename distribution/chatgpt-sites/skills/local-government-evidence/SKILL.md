---
name: local-government-evidence
description: 지방공무원이 지방의회 회의록, 지방예산, 조례·시행규칙의 공식 근거를 함께 확인하고 업무 검토자료를 만들 때 사용합니다.
---

이 스킬은 지방행정 업무의 **근거 확인과 초안 작성**을 돕는다. 결론을 먼저 만들고 근거를 끼워 맞추지 말고, 실제 조회한 자료를 중심으로 답한다.

1. 의회·예산·조례 중 한 분야 질문이면 가장 직접적인 도구부터 사용한다.
2. 두 분야 이상이 섞이면 `local_workflow_plan`으로 지역·기간·기준일·필요 근거를 먼저 정리한다.
3. 실제 읽은 원문, 링크만 확보한 자료, 확인하지 못한 사항을 구분한다.
4. 검색 0건이나 API 실패를 자료 없음·예산 0원·조례 미제정으로 단정하지 않는다.
5. 의원 개인의 성향·평가·순위를 만들지 않는다.
6. 다른 지자체 조례는 비교자료일 뿐 사용자 지자체에 직접 적용되는 근거로 취급하지 않는다.
7. 예산액·집행액·계약액, 본예산·추경·결산, 원·천원·백만원 단위를 구분한다.
8. 조례 검토 결과는 담당자 검토용이며 적법성 승인·의결·공포·전자결재를 대신하지 않는다.

의회 근거 묶음은 `council_evidence_bundle`, 원문 확인은 `council_read_source`, 회기 준비는 `council_session_ready_pack`을 우선 검토한다.

예산은 `budget_api_catalog` → `budget_fetch_api` → 필요 시 `budget_calculate` 순으로 사용한다.

조례는 `ordinance_search` → `ordinance_get_document`로 정식 제명·기관·시행일·버전을 확인하고, 신규사업은 `ordinance_review_project`, 개정 초안은 `ordinance_draft_amendment`, 절차 점검은 `ordinance_guide`를 사용한다.

복합 검토 출력은 **확인 범위 → 확인된 사실 → 업무상 해석 → 미확인 사항 → 다음 조치 → 공식 출처** 순서를 기본으로 한다. 필요할 때 `local_evidence_review`로 누락을 점검하되 원문 사실 검증 자체로 취급하지 않는다.
