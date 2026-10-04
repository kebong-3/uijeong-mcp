# 공개 호출 계약 — 4.1.4-public.1

운영 endpoint: `https://uijeong-mcp.onrender.com/mcp`. 인증 없음, 공개자료 읽기 전용. MCP SDK 1.30.0, stateless Streamable HTTP JSON. initialize → tools/list → tools/call을 POST로 전송한다. 독립 GET은 405이며 장애가 아니다. 원문 제한 초과는 정상 입력 거절이다.

| 도구/인자 | 허용 범위 | 이어읽기 |
|---|---|---|
| council_read_source.max_turns | 정수 1~80 | next_start_turn / next_start_char |
| council_read_source.max_chars | 정수 100~24000 | 같은 ref에 반환 커서 사용 |
| ordinance_get_document.limit | 정수 1~30 | coverage.next_offset |
| ordinance_get_document.max_chars | 정수 200~5000 | coverage.next_start_char |
| ordinance_get_document.offset / start_char | 정수 0 이상 | 선택 section 별도 열람 |
| council_evidence_bundle.max_docs | 공개 서버 1~6 | source_offset 또는 snapshot 이어보기 |
| council_evidence_bundle.limit | 정수 1~30 | next_item_offset |

실제 도구 명세는 운영 tools/list가 기준이다. 스키마 경계에서의 거절은 실패 필드와 허용값을 SDK가 표시하고, 직접 함수 호출의 입력 거절도 validation.field/value/allowed를 제공한다. max_turns=140 및 조례 max_chars=8000은 금지된다. 상한을 올리기 위해 제한을 우회하지 말고 커서를 사용한다.

- `search(query)`는 자연어 의회명을 식별하고 동일 회의록 근거 엔진을 사용한다. 모호한 광주·광주시·중구·서구는 시·도를 명시한다. 반환된 ID만 `fetch(id)`에 전달한다.
- CLIK이 문서 링크를 제공하지 않으면 search 제목에 **원문링크 미제공**을 표시하며 URL은 공식 서비스 홈페이지다. fetch.metadata의 url_kind=OFFICIAL_SERVICE_PORTAL, direct_document_url=false를 보존한다. 이를 문서별 직접 원문 링크라고 인용하지 않는다. 문서 ID와 파싱 발언번호는 실제 조회 위치이며 원본 쪽수·앵커가 아니다.
- 동일 canonical event_id는 한 번만 반환한다. matched_queries는 검색 표현 출처 목록이며 독립 지적 건수가 아니다. 수정 본문은 body hash에 따라 별도 record/event로 남는다.
- local_workflow_plan은 실행 없는 계획이다. arguments_template는 설명을 포함할 수 있으며 executable_calls만 실행용 인자다. 여러 예산단계 요청은 단일 현액 조회로 완료되지 않는다.
- council_context_pack의 discovery_candidates/linked_review는 공식 회의록에 위치가 있는 명칭으로 후속 조회한 후보, 미확인 관계, 출처별 상태를 제공한다. 같은 사업·상위사업 관계, 금액 귀속, 적법성을 자동 인증하지 않는다. 후속 법규 조회는 ordinance 도구와 같은 LawClient 검색·파서를 사용하고 재정은 같은 finance context를 사용한다.
- requested_stage_supported는 데이터셋 제공 단계이며 requested_stage_verified는 해당 단계 자료가 반환되었는지다. amount_verified=false는 단위·예산서 대조가 남았음을 뜻한다. EMPTY는 사업 없음·0원·미제정이 아니다.
- PARTIAL은 일부 실패·범위 제한·후보 관계 미확인을 보존한다. ERROR/unavailable은 조회 실패, INVALID_INPUT은 정상 범위 거절, NEEDS_CONTEXT는 누락정보, PLAN_ONLY/METADATA_REVIEW_ONLY는 실제 근거 조회나 사실 인증이 아니다.

조문 원시 번호의 긴 숫자는 공개 명세에 없는 인코딩을 추측해 해독하지 않는다. 본문 시작 조문 표제를 사용해 label/key를 맞추고 raw_number/source_heading/number_source를 보존한다. 식별 불가·불일치이면 후속 비교·입안을 차단한다. 본문 조회 명세: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=ordinInfoGuide

지역 정규화는 배포에 포함된 날짜 명시 등록표의 고유 식별자 기준이다. 법제처·지방재정 기관코드와 같은 코드라고 가정하지 않는다. 행정구역의 법적 유효기간·전국 코드 교차표 검증을 완료한 것은 아니다.
