# 2026-10-05 복원 작업 인수인계

## 이번 배포 판정

**예정 버전은 `4.1.5-public.1`이며 최종 배포 판정은 PENDING이다.** 이 문서의 예정값은 실제 배포 결과가 아니다. 구현, 고정시험, 실제 MCP 전송, 운영 데이터 조회를 각각 확인한 뒤 아래 표를 갱신한다.

| 항목 | 이번 작업 결과 |
|---|---|
| 저장소 / 운영 브랜치 | `kebong-3/uijeong-mcp` / `main` |
| 변경 기준 commit | `305c0468374b44377966870b5cb6b34132de648f` (`4.1.4-public.4`) |
| 예정 버전 | `4.1.5-public.1` |
| 최종 commit | PENDING |
| Render 서비스 ID / 배포 ID | PENDING |
| 배포 완료 시각 | PENDING |
| 운영 MCP | `https://uijeong-mcp.onrender.com/mcp` |
| 실제 SDK / 협상 프로토콜 | PENDING |
| 실제 공개 도구 수 | PENDING (기존 40개 계약 유지 예정) |
| 실제 schema SHA-256 | PENDING |
| 실제 runtime fingerprint / manifest 판정 | PENDING |
| 최종 고정 회귀시험 | PENDING |
| 운영 실호출 / 수용검사 | PENDING |
| API 키·환경·요금제·인증 변경 | PENDING (최종 변경 내역 대조 필요) |
| 별도 Sites 변경 여부 | PENDING (이번 목표는 기존 Render 운영본 보완) |

## 원요청 8개 산출물

| 번호 | 산출물 | 위치 | 완료 판정 기준 |
|---|---|---|---|
| 1 | 현재상태 비교표 | [CURRENT_STATE.md](CURRENT_STATE.md) | 이전 완료·이번 수정·잔여 범위 구분 |
| 2 | 결함 목록 | [DEFECTS.md](DEFECTS.md) | 입력·관측·영향·수정·회귀 증거 연결 |
| 3 | 실제 변경 코드·diff·테스트 | 이 저장소의 최종 commit; 변경파일·diff 증거 PENDING | 설명과 실제 변경 일치, 기존 운영 코드를 기준으로 적용 |
| 4 | 호출·출력 명세 | [공개 호출 계약](../public-call-contracts.md), [EXAMPLES.md](EXAMPLES.md); 새 tools/list 증거 PENDING | 공개 schema와 실제 허용값·오류·이어읽기 일치 |
| 5 | 검증 결과 | 이 문서의 검증표, [DEFECTS.md](DEFECTS.md); 원시 결과 PENDING | 고정/전송/실조회/플랫폼/미실행을 구분 |
| 6 | 배포 인수인계 | 이 문서, [release-status.json](release-status.json) | commit·실제 배포·hash·설정·복구 경로 확인 |
| 7 | 사용자 실제 예시 | [EXAMPLES.md](EXAMPLES.md), [example-calls.json](example-calls.json); 실제 결과 PENDING | 부서 의회대응·사업예산·조례·통합 각각 실제 출력 |
| 8 | 잔여 과제 | [CURRENT_STATE.md](CURRENT_STATE.md)의 남은 범위 | 기능 미완·자료 미확인·시험 미실행을 구분 |

## 검증 단계별 결과

| 검증 층위 | 2026-10-04 이전 완료 기록 | 2026-10-05 이번 결과 |
|---|---|---|
| 고정 fixture·회귀시험 | 756개 통과 | PENDING |
| 배포된 원시 MCP 수용조건 | 24개 조건 통과 | PENDING |
| 실제 SDK 새 연결 | 2회, 각 도구 40개·계산 성공 | PENDING |
| 기존 ChatGPT Render 연결 | status의 버전·commit·manifest 확인 | PENDING |
| 실제 의회·예산·조례·통합 예시 | 제한된 수원 자료, 부서 실제 예시 미포함 | PENDING |
| 40개 도구 live 전수·다중계정·전국 | 미실행 | PENDING — 별도 실행기록 없으면 미실행으로 유지 |

이번 수정 전 운영 재현은 2026-10-05의 `verification-before/` 기록으로 남겼다. 재정 공개 인자 미적용, 후보 발견 뒤 `EMPTY` 잔류, 불필요 부가 호출을 확인했으며 [CURRENT_STATE.md](CURRENT_STATE.md)에 선별 관측을 적었다. 이 기록과 새 배포 후 결과를 혼합하지 않는다.

성공한 `initialize`, `tools/list` 또는 `council_status`만으로 실제 자료 조회 성공을 판정하지 않는다. 반대로 입력 상한 초과의 정상 거절, 검색 0건, 해당 날짜 자료 미제공을 시스템 장애에 합산하지 않는다. `PARTIAL`에는 반환 근거와 남은 조회범위를 함께 제시한다.

### 40개 도구의 제한된 최소입력 검증

[scripts/verify_recovery.py](../../scripts/verify_recovery.py)는 실제 SDK로 공개 목록을 받고 입력 schema를 검증한 뒤 호출을 순차 실행한다. 앞 호출이 반환한 문서·스냅샷 식별자를 다음 호출에서 사용하며, 필요한 값이 없으면 의존성 미충족으로 미실행 처리한다. 별도 SDK 세션으로 재접속과 0기준 계산도 확인한다.

입력 inventory 및 최종 실행 결과는 **PENDING**이다. 검사기가 작성됐다는 사실을 40개 도구의 실행 성공으로 표현하지 않는다. 결과는 `RETURNED`, `RETURNED_WITH_SCOPE`, `EXPLICIT_SUPPORT_LIMITATION`, `INVALID_TEST_INPUT`, `TOOL_ERROR`, `TRANSPORT_OR_SDK_ERROR`, `UNEXECUTED_INPUT_OR_DEPENDENCY`로 구분한다. 모든 도구가 한 번 응답하더라도 각 업무의 정확도·전국 양성자료·장시간 안정성을 전수 검증한 것은 아니다.

## 외부 계약과 운영 보존

- 공개 읽기 전용으로 필요한 공식 자료를 조회하고 입력값을 검산한다. 별도 유료 LLM 호출을 기본 처리로 추가하지 않는다.
- 기존 공개 도구 이름과 유효 입력의 동작을 유지한다. 재정 `search_terms`는 선택 인자로 추가하고 미지정 호출과 호환해야 한다.
- 추가 검색어를 받았더라도 원명·표기 변형을 포함한 총 표현 한도로 일부를 실행하지 못할 수 있다. `search_strategy`의 요청·계획·제외·미시도 항목 및 coverage를 보고 남은 검색을 확인한다.
- 자료·원문·관련 후보·동일사업·단위·예산단계·법규 적용 검증을 구분한다. 입력 계산을 공식 편성액 확인으로 표시하지 않는다.
- 조례의 관할은 각 결과 행을 공통 지역 식별로 대조한다. 외지 조례는 비교 후보이고 현지 법적 근거로 자동 승격하지 않는다. 모호한 명시 관할은 조회 전 해결한다.
- 실제 `tools/list`에서 새 인자가 보이는지 확인한다. 계정별 스키마 캐시는 실제 해당 연결에서 확인하기 전 완료로 표시하지 않는다.
- 원문 읽기 `max_turns` 1~80, `max_chars` 100~24000; 조례 읽기 `limit` 1~30, `max_chars` 200~5000의 기존 공개 범위와 이어읽기를 보존한다.
- 구형 법규 검색과 공개 `ordinance_search`의 페이지 크기가 다르면 복구는 공개 검색 1페이지부터 다시 시작한다. `RESTART_WITH_PUBLIC_SEARCH`를 같은 페이지 위치의 연속 조회로 오해하지 않는다.
- 무상태 JSON MCP의 독립 GET 응답 `405`는 단독 장애 증거가 아니다. 실제 지원 여부는 POST 초기화·도구 목록·도구 실행으로 확인한다.

## 별도 Sites 프로젝트 구분

기존 Sites 프로젝트 ID는 `appgprj_6abe06fa1d348191b20f39b637a3426b`다. 복원 당시 `/workspace/sites/local-government-evidence`는 native 14개 도구의 별도 Worker이며 로컬 git commit은 `f536621402526018881a6c1655924530bb2dba1a`였다. Render 40개 운영 도구를 해당 이식본으로 대체한 기록은 없다. 이번 Render 배포의 성공을 Sites 플러그인 전체 갱신·다른 계정 설치 성공으로 표현하지 않는다.

## 복구 기준

이번 버전에 문제가 생기면 우선 직전 검증본 `4.1.4-public.4`, commit `305c0468374b44377966870b5cb6b34132de648f`, Render 배포 `dep-db160vgjo6nc73a7on8g`를 복구 기준으로 삼는다. 실제 Render 배포 목록에서 해당 배포와 현재 상태를 대조한 뒤 rollback 또는 이번 변경의 revert commit으로 복구한다. 이 문서 작성만으로 rollback을 수행한 것은 아니다. 강제 push나 이전 부분 다운로드 전체 덮어쓰기는 복구 절차에 포함하지 않는다.

## 최종 작성자가 채울 항목

1. 위 운영 결과표와 `release-status.json`의 PENDING 값을 실제 결과로 갱신한다.
2. `DEFECTS.md`의 8개 결함에 변경파일·테스트 이름·실호출 증거를 연결한다.
3. 새 `tools/list`에서 공개 재정 `search_terms`와 기존 호출범위를 확인하고 명세에 반영한다.
4. `EXAMPLES.md`에 실제 4분야 출력의 읽기 쉬운 요약과 해당 원시 결과 위치를 기록한다.
5. 남은 원천자료·일반 기능·미실행 시험을 완료 성과에 섞지 않는다. 원요청 8개 산출물을 각각 추적할 수 있어야 한다.
