# 2026-10-05 결함 및 수정 추적

예정 버전: `4.1.5-public.1`
최종 commit / 시험 / 배포: **PENDING**

아래 심각도는 이번 작업의 우선순위다. P0는 발언·금액·출처의 오귀속 또는 잘못된 확정으로 이어질 수 있는 문제, P1은 조회 누락·호출 낭비·결과 오독을 일으키는 문제다. 과거 수정 내용과 이번 수정 대상을 구분한다.

## 이번에 확인한 결함

| ID / 심각도 | 관측과 재현 조건 | 업무 영향 | 수정·회귀 합격 기준 | 수정 위치 / 최종 상태 |
|---|---|---|---|---|
| REC-01 / P1 | 내부 재정 조회의 `search_terms`가 공개 schema에 없고 실행에 전달되지 않음. 오늘 운영 재현에서도 추가 필드를 보냈지만 실제 검색 시도는 원명 1개뿐 | 정책 브랜드명 0건 이후의 공식 사업명 탐색이 끊김 | 공개 schema에 optional `search_terms`를 선언하고 내부 함수에 전달. 생략 호출은 기존과 동일. 타입·길이를 일관되게 검증하고 전체 표현 한도로 미실행한 부분은 REC-08 기준으로 표시 | `council_extensions.py`; 최종 시험 `PENDING` |
| REC-02 / P1 | 후속 조회로 법규·재정 후보를 발견해도 `linked_review` 요약 `status`에 최초 `EMPTY`가 남음 | 정상적으로 확보한 후보를 자료 없음으로 오독 | 최초 조회 상태와 통합 후 최종 상태를 구분. 후보가 있으면 발견 사실을 표시하되 단위·동일사업·적용 검증 false를 보존. 응답 축약 후에도 상태·후보수·식별자 일치 | 통합 결과 조립·축약 경로; 패치·시험 `PENDING` |
| REC-03 / P1 | 기본 `council_context_pack`에서 요청하지 않은 `member_record_discovery`, `policy_background` 단계가 실행됨 | 조회 지연과 불필요한 출처 호출, 질문 범위 확대 | 기본 통합 요청은 필요한 경로만 실행. 생략한 단계는 상태와 사유를 표시. 의회·법규·재정의 요청된 근거 탐색은 유지 | `v3_reliability.py` 등 실제 통합 경로; 패치·시험 `PENDING` |
| REC-04 / P1 | 법규 첫 페이지에 해당 지역 후보가 없지만 다음 페이지가 남은 상황에서 `EMPTY`를 반환. 구형 조회와 공개 검색의 페이지 크기가 다르면 같은 페이지 번호로 복구할 때 자료 누락 가능 | 검색을 끝까지 확인하지 않은 결과가 조례 부재로 읽히거나, 복구 중 중간 후보를 빠뜨림 | 남은 페이지를 `PARTIAL`로 표시. 복구는 `RESTART_WITH_PUBLIC_SEARCH`로 공개 검색의 1페이지부터 시작함을 명시. 서로 다른 페이지 크기의 페이지 번호를 직접 변환하지 않음. 다른 지역을 대신 채택하지 않음 | `legal_context.py`, `v3_reliability.py`; 최종 시험 `PENDING` |
| REC-05 / P0 | 통합 후보 요약에서 재정자료의 회계·실제 자료 기준일이 빠짐 | 다른 회계·기준일의 금액 비교 또는 중복 합산 위험 | 원천이 제공한 회계·요청일·실제 기준일·사업코드·연도·단계·단위와 확인상태를 요약·재조회 경로에 보존. 없는 값은 미확인으로 남김 | 후보 요약·`v3_reliability.py` 등; 패치·시험 `PENDING` |
| REC-06 / P0 | 독립적인 정식 업무보고가 앞 의원 질문의 집행부 답변으로 연결됨 | 실제 답변 취지·약속·책임부서의 오귀속 | 질문 뒤 정식보고가 시작되면 앞 QA 답변의 수집을 종료. 정식보고 자체와 원문 위치는 별도 보존. 정상적인 후속 답변은 유지 | `evidence_core.py`; 패치·시험 `PENDING` |
| REC-07 / P0 | `council_legislation_context`가 응답 전체의 `jurisdiction_match`를 각 조례에 적용. 제명 검색의 수원 조례와 본문 검색의 용인 조례가 함께 오면 모두 현지 조례로 분류될 수 있음 | 다른 지자체의 조례를 해당 사업의 법적 근거로 오인 | shared `same_jurisdiction`으로 매 행의 관할 대조. 외지 조례는 비교 후보로만 분류. `중구` 등 모호한 명시 관할은 검색 전에 후보·오류 반환 | 법규 맥락 조립 경로; 최종 시험 `PENDING` |
| REC-08 / P1 | 추가 검색어 3개를 수용하지만 원명·띄어쓰기 변형을 포함한 총 4개 표현 한도에서 마지막 추가 검색어가 제외됨. 제외 사실이 없으면 요청 전체를 검색한 것으로 보임 | 실제 미검색 용어를 검색 0건으로 오인, 후속 재조회 기회 소실 | 4개 호출 한도는 유지. 요청·계획·실제 시도·제외·미시도 용어를 구분하고 `SEARCH_EXPRESSION_LIMIT` 사유, `PARTIAL`, coverage를 반환. 미검색을 자료 없음으로 바꾸지 않음 | 재정 제한 검색 경로; 최종 시험 `PENDING` |

최종 검증 기록에는 각 행에 대응하는 테스트 파일·함수, 실호출 request_id, 실제 결과를 기록한다. 고정시험 통과를 실제 원천자료 확인으로 대체하지 않는다.

## 오늘 수정 전 실호출 증거

- REC-01: `/workspace/scratch/0f8070660f49/verification-before/council_finance_context.json`. `4.1.4-public.4`, 2026-10-05 22:43:07 KST, request_id `6e815c1e9b904c39a877`. 추가어 `소규모 공동주택`은 시도 목록에 없고 `빌라가꿈관리소`만 조회됨.
- REC-02·03: `/workspace/scratch/0f8070660f49/verification-before/council_context_pack.json`. 법규·재정 `initial_candidates=0`, `discovered_candidates=3`, `status=EMPTY`. `member_record_discovery=COMPLETE`, `policy_background=EMPTY`로 불필요 경로 실행 확인.
- REC-04~08의 분리 재현은 아래 고정시험으로 확인한다. 특히 REC-07의 수원·용인 식별자는 합성 fixture이며 실제 해당 조례 검색을 수행한 기록이 아니다.

## 이전 수정의 유지 조건

| 이전 결함 | 이미 확인한 수정 | 이번 회귀에서 유지할 조건 |
|---|---|---|
| 긴 조문 식별번호를 조번호로 오표기 | 원문 표제 기반 `제5조의2` 식별, 원시번호 별도 보존 | 본문·label·key·근거 조번호 일치, 충돌 시 차단 |
| 본예산·추경을 핵심 사업명으로 사용 | 핵심 대상과 요청 속성·기간 분해 | 사업명에 포함된 '예산'은 훼손하지 않음 |
| 지역명 exact match로 적격 조례 누락 | 등록표 기반 고유 지역 정규화 | 동명지역을 임의 선택하지 않음 |
| 같은 event가 다음 페이지에서 중복 | canonical event 병합·검색경로 보존 | 수정 원문·다른 회의의 독립 발언은 합치지 않음 |
| 표준 search의 짧은 의회명 누락 | 공통 지역 식별과 실제 ID fetch | 실제 반환 ID 사용, 없는 개별 문서 URL 생성 금지 |
| 재정 빈 결과의 verified=true | dataset 지원과 실제 금액 확인을 분리 | EMPTY를 0원이나 검증된 금액으로 바꾸지 않음 |
| 응답 축약이 후속 검색 결과 삭제 | 후보 식별자·관계·원문 위치·재조회 경로 보존 | 상세 표시수와 전체 후보수의 의미 구분 |

## 시험 중 실패 기록의 해석

이전 작업의 재사용 fixture SQLite에서 `database disk image is malformed` 오류가 17건 발생했다. 별도 isolated DB에서 전체 756개가 통과했으나 최초 손상 원인은 확정하지 못했다. 이 기록만으로 Render 운영 DB가 손상됐다고 결론내리지 않는다. 이전 실패 로그는 `review-pytest-local-state-failure.txt`, 재시험 로그는 `review-pytest-final.txt`다.

이번 결과에는 테스트 실패가 있으면 원인, 수정, 재실행 결과를 함께 남긴다. 같은 실패를 숨기기 위해 시험을 제외하거나 과거 통과 수치를 재사용하지 않는다.

## 최종 검증 기록 — PENDING

| 항목 | 증거 파일 / 실행 시각 | 결과 |
|---|---|---|
| REC-01 공개 인자·schema·전달 | [test_finance_public_search_terms.py](../../tests/test_finance_public_search_terms.py) — 선언·실제 SDK 전달·생략 호환·잘못된 값 거절 | 최종 실행 PENDING |
| REC-02 후속 후보 발견 상태·축약 | [test_recovery_context_summary.py](../../tests/test_recovery_context_summary.py), `test_followup_candidates_survive_initial_empty_or_failure` | 최종 실행 PENDING |
| REC-03 요청하지 않은 경로 생략 | 같은 파일의 `test_background_requests_are_opt_in_and_traceable` | 최종 실행 PENDING |
| REC-04 법규 페이지 부분범위·복구 | [test_recovery_contract_edges.py](../../tests/test_recovery_contract_edges.py), `test_unread_legal_search_page_does_not_become_empty_local_search`, `test_legal_recovery_does_not_skip_candidates_when_adapter_page_size_changes` | 최종 실행 PENDING |
| REC-05 재정 회계·기준일 보존 | 같은 파일의 `test_fiscal_candidates_keep_account_snapshot_and_government_identity` — 서로 다른 회계와 축약 후 식별자 유지 | 최종 실행 PENDING |
| REC-06 QA와 정식보고 경계 | [test_recovery_speech_boundaries.py](../../tests/test_recovery_speech_boundaries.py) — 정식보고 보존·QA 제외·정상 답변 유지 | 최종 실행 PENDING |
| REC-07 조례 행별 관할·모호지역 | [test_legislation_jurisdiction_boundaries.py](../../tests/test_legislation_jurisdiction_boundaries.py) — 수원·용인 행 구분, 모호지역 상류 요청 전 거절 | 최종 실행 PENDING |
| REC-08 제한 검색의 제외어 표시 | [test_recovery_fiscal_search_scope.py](../../tests/test_recovery_fiscal_search_scope.py), `test_accepted_extra_term_is_not_silently_lost_at_expression_limit` | 최종 실행 PENDING |
| 기존 전체 고정 회귀시험 | PENDING | PENDING |
| 배포본 schema·버전·commit | PENDING | PENDING |
| 실제 4분야 예시 | PENDING | PENDING |
