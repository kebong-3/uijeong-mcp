# 2026-10-05 통합 MCP 최종 인수인계

## 배포와 검증 결과

**최종 운영 버전은 `4.1.5-public.2`다.** 기존 Render 운영본에 코드를 반영하고 실제 배포·MCP 연결·업무 호출까지 확인했다. 833개 고정 회귀시험과 공개 40종 도구의 42회 호출, 수용조건 15개를 통과했다. 최소입력 검증이 다중계정·전국·모든 자료의 정확성을 보장하는 것은 아니다.

| 항목 | 최종 확인 값 |
|---|---|
| 저장소 / 운영 브랜치 | `kebong-3/uijeong-mcp` / `main` |
| 변경 기준 commit | `305c0468374b44377966870b5cb6b34132de648f` (`4.1.4-public.4`) |
| 최종 버전 | `4.1.5-public.2` |
| 코드 commit | `541cd09b95fa233d5bed003045a5b49a28dd5c31` |
| git tree | `767c5c97f851763bae91fc78cbf71eb58c247c94` |
| Render 서비스 | `srv-dalbmfe7bikc73fnnr90` |
| Render 배포 | `dep-db1r2ao473hc739e97e0` |
| 배포 완료 | 2026-10-05 23:17:13 KST (`2026-10-05T14:17:13.618002Z`) |
| 운영 MCP | `https://uijeong-mcp.onrender.com/mcp` |
| 실제 전송 / 협상 프로토콜 | MCP SDK Streamable HTTP / `2025-11-25` |
| 서버 공개 도구 / 현재 대화 로드 메타데이터 | SDK `tools/list` 40개 / 기존 호스트 연결 21개·이전 입력 명세 관측 |
| schema SHA-256 | `4507baf3e18b62e927b6ce7c5530aa658a77afdd0efb4774509a864485fa0b26` |
| runtime fingerprint | `1935000553e03ada1c07ef11a0a611cd2f302882176d4991f68662654eea10c3` |
| runtime 무결성 | 80개 파일 `MATCH` |
| 고정시험 | 833개 통과, 33.78초 |
| 실제 최소입력 | 42회 응답·40종 도구, 도구 오류·의존성 미실행 0 |
| 수용조건 / 별도 SDK 재접속 | 15개 통과 / 재접속·40도구·0기준 계산 성공 |
| API 키·환경변수·요금제·인증·Sites 변경 | 없음 |

[Render 배포 기록](evidence/after-r2/render-deployment.json), [기존 연결 status](evidence/after-r2/native-status.json), [SDK 실제 tools/list](evidence/after-r2/tools-list.json), [운영 검증 요약](evidence/after-r2/summary.json)을 대조한다. 후속 문서 정리 commit과 위의 실제 운영 코드 commit을 혼동하지 않는다.

## 원요청 8개 산출물

| 번호 | 산출물 | 바로 확인할 파일 | 내용 |
|---|---|---|---|
| 1 | 현재상태 비교표 | [CURRENT_STATE.md](CURRENT_STATE.md) | 이전 완료·이번 수정·최종 실측·확인 범위 |
| 2 | 결함 목록 | [DEFECTS.md](DEFECTS.md) | REC-01~10 및 VFY-01의 관측·원인·수정·검증 |
| 3 | 실제 변경 코드·diff·테스트 | [code-changes.patch](evidence/code-changes.patch), [파일별 변경·hash](evidence/code-change-index.json), [변경 통계](evidence/code-change-stat.txt) | 이전 기준→최종 코드의 26개 변경 경로. 보고서·원시 근거 폴더는 별도 제공 |
| 4 | 호출·출력 명세 | [공개 호출 계약](../public-call-contracts.md), [실제 schema](evidence/after-r2/tools-list.json), [실제 예시 입력](example-calls.json) | 인자 범위·기본값·오류·조회범위·이어읽기 |
| 5 | 검증 결과 | [고정시험](evidence/pytest-r2-final.txt), [실호출 요약](evidence/after-r2/summary.json), [실제 다음 비교 페이지](evidence/after-r2/calls/dependency_compare_next_page.json) | 고정·실시간·전송·예상 상태·재접속을 구분 |
| 6 | 배포 인수인계 | 이 문서, [release-status.json](release-status.json) | 버전·commit·hash·설정 보존·복구 기준 |
| 7 | 사용자 실제 예시 | [EXAMPLES.md](EXAMPLES.md), [example-calls.json](example-calls.json) | 부서 의회대응·사업예산·조례·통합의 실제 입력·출력·원문 위치 |
| 8 | 잔여 과제 | [CURRENT_STATE.md](CURRENT_STATE.md)의 마지막 표 | 일반 자동 수집·전국 코드·다중계정 등의 미구현·미검증 범위 |

`code-changes.patch`는 검토용 실제 git diff이며 의사코드가 아니다. `docs/recovery-20261005/`의 보고서와 원시 기록은 patch에서 제외해 별도로 보존했다. 최종 코드 재현의 기준은 위 git commit이다.

## 단계별 검증과 실패 처리

| 단계 | 결과 | 근거 |
|---|---|---|
| 이전 `4.1.4-public.4` | 756개 고정시험·24개 수용조건 | [이전 수용시험](evidence/baseline-414/review-live-acceptance.json), [고정시험](evidence/baseline-414/review-pytest-final.txt). 이번 시험에 합산하지 않음 |
| 1차 `4.1.5-public.1` 고정시험 | 791개 통과 | [1차 고정시험](evidence/pytest-final.txt) |
| 1차 실제 MCP | 41회 계획, 39회 응답·38종 도구. 오류 3회·의존성 미실행 2회로 `REVIEW_REQUIRED` | [1차 실호출](evidence/after-r1/summary.json) |
| 후속 수정 첫 고정시험 | 테스트용 후단 객체의 `ClikError` 속성 가정으로 3개 실패·826개 통과 | [실패 로그](evidence/pytest-r2-first-failure.txt) |
| 해당 회귀 수정 | 829개 통과. 구형 프로필 보호 시험 추가 후 833개 통과 | [중간 로그](evidence/pytest-r2-intermediate-829.txt), [최종 로그](evidence/pytest-r2-final.txt) |
| 최종 실제 MCP | 42회·40종 도구 응답, `RETURNED` 26회·`RETURNED_WITH_SCOPE` 16회, 오류·미실행 0, 15개 수용조건 통과 | [최종 실호출](evidence/after-r2/summary.json) |
| 실제 부서 양성 예시 | 조회된 회의 메타데이터로 날짜·위원회를 지정해 실질 질의 269→답변 270 확인 | [지정 회의의 부서 조회](evidence/after-r2/department-located-meeting.json) |

`RETURNED`는 검증기 분류명이며 plain text의 `PARTIAL` 응답도 포함한다. 완전한 자료확인 26건을 뜻하지 않는다. 1차 실패는 최종 성공 결과로 대체하지 않고 별도 폴더에 보존했다. 검사기 문제 때문에 실행하지 못했던 개정 초안·근거검토는 원문·조문·hash 조건을 유지한 상태로 최종 실제 호출했다. 검증용 개정문은 실제 개정·공포가 아닌 기계적 초안이다.

## 공개 계약에서 달라진 부분

| 도구 / 범위 | 실제 계약 |
|---|---|
| `council_finance_context.search_terms` | 선택 인자, 최대 3개 문자열, 각 1~100자. 생략 호출과 호환. 총 검색표현 한도 때문에 실행하지 않은 용어는 사유·coverage로 표시 |
| `council_context_pack` 부가조회 | `include_member_records=false`, `include_policy_background=false`가 기본. 필요할 때만 명시 요청 |
| `ordinance_compare` | `offset≥0`, `limit=1~10`(기본 3), `max_chars=100~1500`(기본 400). 반환 continuation과 `expected_hashes`로 다음 구간 조회 |
| `council_read_source` | `max_turns=1~80`, `max_chars=100~24000`; 반환 turn/char 커서로 이어읽기 |
| `ordinance_get_document` | `limit=1~30`, `max_chars=200~5000`; section별 offset/start_char로 이어읽기 |
| 법규 검색 복구 | 구형 조회와 공개 검색의 페이지 크기가 다르면 `RESTART_WITH_PUBLIC_SEARCH`로 공개 검색 1페이지부터 재개 |
| CLIK 제한 복구 | public 프로필의 확인된 내용검색 `ERROR11` 조합만 원본 실패 후 공백 제거 표현 1회 재시도. 원문 질의·실제 질의·실패·부분범위 보존 |

CLIK 제공기관의 원래 오류가 해결된 것은 아니다. 인증·쿼터·네트워크 오류, 다른 검색범위에는 위 공백 복구를 적용하지 않는다. full/lite/core/work의 기존 오류 동작도 바꾸지 않았다.

검증 inventory는 [recovery_minimum_calls.json](../../scripts/recovery_minimum_calls.json), 실행기는 [verify_recovery.py](../../scripts/verify_recovery.py)다. 40종 도구 외에 비교 조례 검색과 실제 비교 다음 페이지를 추가해 42회를 실행했다. 앞 응답이 반환한 ID·판본·hash를 다음 입력에 사용했다. 동일 판본 비교는 변동 없음 대조이며 과거·현재 법규 차이를 실제 검증한 것으로 보고하지 않는다.

## 운영 관측과 보존 사항

최종 [health 응답](evidence/after-r2/health.json)은 HTTP 200과 `.2` 버전을 확인했다. [Render 오류 로그 조회](evidence/after-r2/render-errors.json)에서 2026-10-05 14:16:11~14:21:29 UTC 구간의 error 수준 로그는 0건이었다. 이는 그 시각 범위와 로그 수준의 관측이며 장시간 무오류 보장이 아니다.

공개 읽기 전용, 기존 인증 방식, 공식 API 키, 요금제·환경 설정을 유지했다. 별도 유료 LLM 호출을 기본 처리로 추가하지 않았다. 원문·후보·동일사업·단위·예산단계·법규 적용의 확인 수준을 구분한다. 계획·계산·메타데이터 검토·개정 초안을 공식 예산 확정이나 법적 승인으로 표시하지 않는다.

독립 GET `405`만으로 MCP 장애를 판단하지 않는다. 실제 지원 여부는 POST 초기화·도구 목록·도구 실행으로 확인했다. 별도 Sites 프로젝트 `appgprj_6abe06fa1d348191b20f39b637a3426b`의 native 14개 도구 이식본은 이번에 변경하지 않았다. Render 검증을 모든 ChatGPT 계정의 설치·스키마 캐시 갱신 또는 Sites 전체 갱신으로 표현하지 않는다.

## 현재 대화의 연결 메타데이터

[현재 호스트 관측](evidence/after-r2/host-metadata-scope.json)에서 이 대화에 로드된 `서구의회` 연결은 21개 도구를 노출했고, `council_finance_context.search_terms`와 `council_context_pack`의 선택 배경 인자는 아직 이전 명세였다. 같은 연결의 status는 새 서버 `.2`를 확인했고, 별도 SDK의 실제 서버 `tools/list`는 40개 도구와 새 입력 명세를 확인했다. 서버 반영과 현재 대화의 메타데이터 갱신을 각각 기록한다.

이 세션에 제공된 관리 기능에는 Refresh가 없으므로 **호스트 연결 Refresh는 수행하지 않았다.** 현재 연결이 개발자 연결인지 게시 플러그인인지, 다른 계정에도 같은 현상이 있는지, 메타데이터 차이의 원인이 무엇인지는 확정하지 않았다.

개발자 모드 MCP 연결이라면 [공식 연결 안내](https://developers.openai.com/plugins/deploy/connect-chatgpt)에 따라 ChatGPT의 **Plugins → 해당 연결 → Refresh → 변경 메타데이터 확인 → 새 대화에서 재시험** 순서로 확인한다. 게시된 플러그인은 연속 검토와 별도 릴리스 절차를 따르므로 이 개발자 연결 안내를 모든 배포 유형의 갱신 절차로 적용하지 않는다. 갱신 후 확인할 항목은 40개 도구, 재정 `search_terms`, 통합의 두 선택 배경 인자다.

## 복구 기준

이번 변경 이전의 검증 기준은 `4.1.4-public.4`, commit `305c0468374b44377966870b5cb6b34132de648f`, Render 배포 `dep-db160vgjo6nc73a7on8g`다. 실제 문제가 발생하면 배포 목록·현재 commit·오류를 대조한 뒤 해당 기준으로 rollback하거나 이번 변경을 되돌리는 새 revert commit을 사용한다. 이번 작업에서 rollback은 실행하지 않았다. 부분 다운로드 폴더로 저장소 전체를 덮거나 강제 push하는 방식은 사용하지 않았다.
