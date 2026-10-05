# 결함·수정·검증 최종 기록

최종 버전 `4.1.5-public.2`, 코드 commit `541cd09b95fa233d5bed003045a5b49a28dd5c31`. 고정 회귀시험 **833개**와 실제 40종 도구의 **42회 호출·수용조건 15개**가 통과했다. 근거는 [최종 시험 로그](evidence/pytest-r2-final.txt), [최종 운영 검증](evidence/after-r2/summary.json), [실제 코드 diff](evidence/code-changes.patch)다.

P0는 발언·금액·출처·지역의 잘못된 귀속으로 이어질 수 있는 문제, P1은 조회 누락·호출 낭비·중단·결과 오독을 일으키는 문제로 분류했다. VFY-01은 제품 기능과 구분한 검증기 결함이다.

## 수정 추적

| ID / 우선순위 | 재현·관측 | 실제 수정 | 회귀·운영 확인 |
|---|---|---|---|
| REC-01 / P1 | 공개 재정 schema에 `search_terms`가 없어 추가 필드를 보내도 원명만 검색 | `council_extensions.py`에 선택 인자·동일 입력검증·내부 전달. 최대 3개, 각 1~100자 | `test_finance_public_search_terms.py`; 실제 추가어로 관련 사업 3개 발견 |
| REC-02 / P1 | 후속 법규·재정 후보 각 3개를 찾고도 대표 요약 `EMPTY` | 초기 상태·발견 단계·최종 `PARTIAL`·`CANDIDATES_FOUND`를 구분하고 축약 뒤에도 유지 | `test_recovery_context_summary.py`; 최종 통합 결과와 수용조건 확인 |
| REC-03 / P1 | 기본 통합 요청에서 의원자료·정책배경 자동 조회 | 두 부가조회 선택 인자를 기본 false로 두고 생략 사유·trace 반환 | 같은 테스트의 opt-in/기본 생략 조건; 실제 두 단계 `SKIPPED` |
| REC-04 / P1 | 법규 첫 페이지에 해당 지역이 없고 뒤 페이지가 남아도 `EMPTY`. 페이지 크기 변경 시 복구 누락 가능 | 부분범위·남은 페이지를 표시. 다른 페이지 크기의 공개 검색은 `RESTART_WITH_PUBLIC_SEARCH`로 1페이지부터 시작 | `test_recovery_contract_edges.py`의 페이지 미완료·복구 테스트 통과 |
| REC-05 / P0 | 재정 후보 축약에서 회계·실제 기준일·기관 식별자가 누락 | 사업코드·연도·기관·회계·실제 기준일을 식별·요약·재조회 인자에 보존 | 같은 테스트에서 다른 회계 2개와 축약 결과 보존. 실제 일반회계·20261004 확인 |
| REC-06 / P0 | 독립 정식 업무보고를 앞 의원 질문의 답변에 연결 | `evidence_core.py`에서 정식보고 시작 시 앞 QA 연결을 종료. 보고 원문과 정상 답변은 보존 | `test_recovery_speech_boundaries.py`; 보고·답변·답변 뒤 새 보고의 경계 테스트 |
| REC-07 / P0 | 법규 응답 전체의 지역 일치값이 각 행에 적용되어 수원·용인 조례가 모두 현지 조례로 분류될 수 있음 | `council_extensions.py`에서 shared `same_jurisdiction`으로 행별 대조. 외지 조례는 비교 후보, 모호 관할은 검색 전 거절 | `test_legislation_jurisdiction_boundaries.py`의 혼합 관할·모호지역 테스트 통과 |
| REC-08 / P1 | 원명·표기 변형 포함 4개 표현 한도에서 추가어 일부가 제외되지만 미검색 사실을 알리지 않음 | 요청·계획·시도·제외·미시도 용어와 `SEARCH_EXPRESSION_LIMIT` 사유·`PARTIAL`·coverage 표시 | `test_recovery_fiscal_search_scope.py`; 한도·미검색·빈 결과의 구분 확인 |
| REC-09 / P1 | 실제 CLIK 공백 포함 내용검색의 `ERROR11`로 반복쟁점·타 의회 사례 도구가 `ERROR` | public 프로필의 해당 조합만 원본 실패 후 공백 제거 표현 1회 재시도. 원본·실제 질의·실패·부분범위·자원 한도 보존 | `test_recovery_clik_query.py`; 같은 운영 입력 두 도구가 `PARTIAL`로 근거·실패 범위를 반환 |
| REC-10 / P1 | 실제 수원·성남 조례 2개 비교가 50,409자 결과 때문에 `OUTPUT_LIMIT` | 비교 결과 페이지·발췌 길이·생략범위·원문 복구를 제공. 판본 hash가 다른 다음 페이지는 차단 | `test_recovery_ordinance_compare.py`; 실제 첫 구간과 다음 구간의 동일 판본·연속 위치 확인 |
| VFY-01 / 검증기 | 전체 조문에서 선택적 `excerpt_location`이 없다는 이유로 후속 ID/hash 추출을 보류해 2개 도구 미실행 | 선택 필드 부재 허용을 명시 조건에만 적용. 원문 전체·정확한 조번호·본문·hash 가드는 유지 | `test_recovery_verifier_preconditions.py` 5개 조건. 실제 개정 초안·메타데이터 검토 호출 성공 |

위 테스트 파일은 모두 저장소의 `tests/`에 있다. 구체적 변경 경로와 최종 파일별 hash는 [code-change-index.json](evidence/code-change-index.json)에 기록했다. 고정 fixture와 실제 원천 응답의 확인 수준은 구분한다.

## 실제 수정 전·후 대조

### 재정 검색어 전달

수정 전 [운영 응답](evidence/before/council_finance_context.json)은 2026-10-05 22:43:07 KST, request_id `6e815c1e9b904c39a877`이다. `search_terms=["소규모 공동주택"]`를 보냈지만 실제 시도는 `빌라가꿈관리소` 1개이고 결과는 `EMPTY`였다.

최종 [운영 응답](evidence/after-r2/calls/council_finance_context.json)은 원명 0건 이후 추가어를 실제 조회하여 수원 관련 사업 3개를 반환했다. 원천 단위·동일사업 확인은 false로 보존했다. 인자를 선언한 것만으로 완료 판정하지 않고 실제 시도 배열을 대조했다.

### 통합 상태와 부가조회

수정 전 [통합 응답](evidence/before/council_context_pack.json)은 후속 후보를 찾았지만 법규·재정 요약이 `EMPTY`였고 의원자료·정책배경을 실행했다. 최종 [통합 응답](evidence/after-r2/calls/council_context_pack.json)은 각 분야 `initial_status=EMPTY`, 최종 `status=PARTIAL`, `candidate_status=CANDIDATES_FOUND`를 함께 보존했다. 부가조회 두 단계는 `SKIPPED`다. `same_project_verified`, 적용·금액 검증, 제출완료는 근거 없이 참으로 바꾸지 않았다.

### CLIK 공백 오류와 제한된 복구

1차 운영본의 [직접 대조 진단](evidence/after-r1/diagnostics/native-clik-space.json)에서 같은 수원·기간에 전체검색 상류 855건, 공백 포함 내용검색 `MINTS_HTML`의 `CLIK_ERRORS ERROR11` 문구, 공백 제거 내용검색 상류 842건을 확인했다. 855와 842는 서로 다른 검색방식의 상류 건수이며 독립 질문수나 같은 결과집합을 뜻하지 않는다.

원천의 오류 자체를 고쳤다고 주장하지 않는다. 확인된 오류 조합에서만 1회 대체 검색하고 원래 실패와 실제 검색어를 공개한다. 인증·쿼터·네트워크·다른 검색범위에는 적용하지 않는다. full/lite/core/work 프로필은 기존 오류 응답을 유지하며 공개 프로필의 복구가 trace 없이 전파되지 않도록 4개 프로필 회귀시험을 추가했다.

최종 같은 입력의 [반복쟁점](evidence/after-r2/calls/council_recurring_issues.json)과 [타 의회 사례](evidence/after-r2/calls/council_peer_cases.json)는 모두 `PARTIAL`로 응답했다. 부분범위를 감춘 완전 성공으로 바꾸지 않았다.

### 조례 비교 이어읽기

1차 [수원·성남 비교](evidence/after-r1/calls/ordinance_compare.json)는 `OUTPUT_LIMIT`였다. 최종 [첫 비교](evidence/after-r2/calls/ordinance_compare.json)는 계산한 대응 후보 12개 중 2개를 반환하고 `next_offset=2`를 제공했다. 해당 continuation을 그대로 사용한 [다음 페이지](evidence/after-r2/calls/dependency_compare_next_page.json)에서 같은 source hash와 이어지는 위치를 확인했다.

계산한 전체 대응 후보와 현재 표시한 구간을 구분한다. 이 실호출은 첫 페이지와 다음 페이지를 확인한 것이며 12개 전 항목의 법적 동등성을 인증한 것이 아니다. 고정시험에서는 전체 페이지의 누락·중복, 정확한 원문 재조회, 판본 변경 차단도 검증했다.

## 실행 중 실패와 최종 판정

| 기록 | 결과 | 처리 |
|---|---|---|
| `.1` 실제 41회 계획 | 응답 39회·38종, 도구 오류 3회, 검증기 의존성 미실행 2회 | [첫 검증](evidence/after-r1/summary.json)을 보존하고 REC-09·10, VFY-01 수정 |
| `.2` 첫 전체 고정시험 | 3개 실패·826개 통과 | 테스트용 `SimpleNamespace` 후단에 `ClikError`가 없다는 속성 가정 확인 |
| 오류 처리 경계 보완 | 829개 통과 | `getattr` 가드로 원래 오류 의미를 유지 |
| 구형 프로필 보호 추가 | 833개 통과 | [최종 고정시험](evidence/pytest-r2-final.txt) |
| `.2` 실제 42회 계획 | 응답 42회·40종, 오류·미실행 0, 수용조건 15개 통과 | [최종 운영 검증 PASS](evidence/after-r2/summary.json) |

시험 중 실패 로그는 [첫 실패](evidence/pytest-r2-first-failure.txt), [829개 중간 결과](evidence/pytest-r2-intermediate-829.txt)에 남아 있다. 이를 운영 DB 장애로 해석하지 않는다. 이전 작업의 재사용 SQLite fixture 손상도 운영 DB 손상의 증거로 확정하지 않았으며 장기간 저장소 평가는 별도 범위다.

## 기존 기능의 유지와 확인 한계

조문 표제·원시번호 구분, 사업명과 본예산·추경 속성의 분리, 지역 별칭·모호성 검사, canonical event 중복 제거, 실제 search ID→fetch, 0기준 증감률, 원문·단위·예산단계·법적 승인 구분을 유지했다. 불확실한 자료 관계를 false로 남긴 것은 결함을 숨긴 표시가 아니라 현재 확보한 근거의 한계다.

공식 예산서의 일반 자동 수집, 전국 기관코드 효력기간, 모든 계정·클라이언트 설치, 전국 양성자료·장시간 운영은 이번 시험에서 완료했다고 주장하지 않는다. 해당 범위는 [CURRENT_STATE.md](CURRENT_STATE.md)에 구체적으로 적었다.

현재 대화에 로드된 호스트 연결의 21개 도구·이전 인자 명세와 실제 서버의 40개 도구·새 명세의 차이도 [별도 관측](evidence/after-r2/host-metadata-scope.json)으로 남겼다. 호스트 Refresh는 이 세션에서 수행하지 않았고, 원인이나 다른 계정 상태를 확정하지 않았다. 서버 수정·검증 완료를 호스트 메타데이터 갱신 완료로 바꾸어 보고하지 않는다.
