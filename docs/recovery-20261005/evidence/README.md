# 검증 근거 보존

이 폴더는 실제 실행기록과 시험 로그를 단계별로 보존한다. 관측 결과를 후속 성공 결과로 덮어쓰지 않는다. JSON 복사 전 인증값 필드와 URL의 인증 파라미터를 점검했으며, 복사한 파일에서 후보 비밀값을 발견하지 않았다. 원시 응답에 포함된 공개 검색·자료·문서 식별자와 hash는 검증 근거로 보존했다.

| 경로 | 버전·시점 | 의미 |
|---|---|---|
| `baseline-414/` | 이전 `4.1.4-public.4`, 2026-10-04 | 이전 배포·native status·756개 고정시험·24개 수용조건·SDK 기록. 이번 결과에 합산하지 않음 |
| `before/` | 2026-10-05, `4.1.4-public.4` | 이번 수정 전 실제 공개 schema, 재정·통합 재현 응답 |
| [pytest-final.txt](pytest-final.txt) | 1차 `4.1.5-public.1` 배포 전 | 791개 고정 회귀시험 통과 로그. 후속 버전 시험 실적이 아님 |
| `after-r1/` | 1차 `4.1.5-public.1`, commit `de2e6f5a7c35448609a22985108515c00dc17d5f` | 실제 MCP SDK 초기화·공개 schema·41개 계획·응답·요약·재접속. 최종 상태 `REVIEW_REQUIRED` |
| `after-r1/diagnostics/` | 같은 1차 운영본 | 공백 포함 CLIK 질의의 전체/내용검색과 공백 제거 내용검색 대조 |
| [pytest-r2-first-failure.txt](pytest-r2-first-failure.txt) | `.2` 수정 중 | 테스트용 후단 객체 속성 가정으로 3개 실패·826개 통과. 원인 해결 전 기록 보존 |
| [pytest-r2-intermediate-829.txt](pytest-r2-intermediate-829.txt) | 해당 회귀 수정 후 | 829개 통과. 이후 구형 프로필 보호 시험 4개 추가 |
| [pytest-r2-final.txt](pytest-r2-final.txt) | 최종 `4.1.5-public.2` 배포 전 | 833개 고정 회귀시험 통과, 33.78초 |
| `after-r2/` | 최종 `4.1.5-public.2`, commit `541cd09b95fa233d5bed003045a5b49a28dd5c31` | 실제 SDK 초기화·40개 schema·42회 호출·15개 수용조건·재접속. 서버 최소입력 검증 `PASS` |
| [code-changes.patch](code-changes.patch) | 이전 `.4`→최종 `.2` 코드 | 실제 git diff. 보고서·원시 근거 폴더 제외 |
| [code-change-index.json](code-change-index.json), [code-change-stat.txt](code-change-stat.txt) | 같은 26개 변경 경로 | 변경 파일·최종 파일 hash·3272개 추가/93개 삭제 |

## 최종 실측의 바로 확인할 파일

| 확인 대상 | 근거 |
|---|---|
| 배포 live·운영 commit·버전 | [Render 배포](after-r2/render-deployment.json), [기존 연결 status](after-r2/native-status.json) |
| 실제 서버의 40개 도구·새 인자 | [SDK tools/list](after-r2/tools-list.json) |
| 42회·40종·15개 수용조건·오류 0·미실행 0 | [최종 요약](after-r2/summary.json)과 그 `calls/` 원시 응답 |
| 재접속·0기준 계산 | [별도 SDK 연결](after-r2/sdk-reconnect.json) |
| 비교 페이지 연속·동일 판본 | [첫 비교](after-r2/calls/ordinance_compare.json), [실제 다음 페이지](after-r2/calls/dependency_compare_next_page.json) |
| 부서별 실질 질의 | [지정 회의의 269→270](after-r2/department-located-meeting.json). [넓은 조회의 제한 결과](after-r2/department-example.json)도 보존 |
| health·구간 오류 로그 | [HTTP 200](after-r2/health.json), [한정 구간 error 0건](after-r2/render-errors.json). 장시간 무오류 보장 아님 |
| 현재 대화의 호스트 메타데이터 | [21개 도구·이전 인자 관측](after-r2/host-metadata-scope.json). 호스트 Refresh 미수행 |

최종 분류는 `RETURNED` 26회와 `RETURNED_WITH_SCOPE` 16회다. `RETURNED`에는 plain text로 부분범위를 알린 응답도 포함된다. 완전한 자료확인 26건을 뜻하지 않는다.

`summary.json`의 `expected_checks`는 기대조건을 검사한 결과다. 해당 원천자료의 사실값을 뜻하지 않는다. 예를 들어 `budget_basis.amount_verified` 검사의 `true`는 실제 반환된 값이 기대한 `false`와 일치했다는 뜻일 수 있다. 사실값은 각 `calls/*.json`의 원시 `result`에서 확인한다.

응답이 있다는 사실, 도구가 오류를 반환하지 않았다는 사실, 실제 자료를 찾았다는 사실, 업무 검토가 끝났다는 사실을 구분한다. 계획·메타데이터 점검·검토 초안·동일 판본 대조를 사실 인증이나 법적 승인으로 보고하지 않는다.

`code-changes.patch`의 SHA-256은 `8759e8007bf5b1c1d0af35b30a68495726cf9d10157bef739935bf2e4cf08b37`이다. 원본 SDK JSON에는 MCP text content와 structuredContent의 동일 자료가 함께 들어갈 수 있으며, 원시 반환 형태를 보존하기 위해 중복을 제거하지 않았다.

최종 검증 결과와 미검증 범위, 호스트 연결의 조건별 메타데이터 갱신 안내는 상위 [HANDOFF.md](../HANDOFF.md)와 [release-status.json](../release-status.json)을 함께 확인한다. 서버 배포·SDK 검증 완료를 모든 호스트 연결이나 계정의 갱신 완료로 해석하지 않는다.
