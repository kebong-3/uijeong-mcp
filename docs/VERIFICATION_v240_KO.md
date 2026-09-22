# 의정소통 MCP 2.4.0-rc.1 개선·검증보고서

기준: 2026년 9월 21일 / 사용자 제공 uijeong-mcp-v2.3.1(1).zip 기반

## 1. 결과

개선 소스를 작성했고, 독립 실행 가능한 기존 시험 **174건**과 신규 시험 **90건**, 총 **264건이 통과**했습니다.
선택 실행에서 실제 SDK를 요구하는 기존 시험 1건은 제외했습니다. 이 1건을 통과에 포함하지 않았습니다.
전체 pytest는 `mcp` 패키지를 불러오는 4개 모듈의 수집 단계에서 중단됐고, 실제 stdio/HTTP 시험도 같은 이유로 시작하지 못했습니다.
따라서 이 결과물은 `2.4.0-rc.1`이며 실제 운영·로그인 검수를 마친 최종 운영판으로 표시하지 않습니다.

| 항목 | 이번 확인 상태 |
|---|---|
| 파이썬 소스 문법 검사 | 통과 |
| 기존 독립 회귀시험 | 174건 통과 |
| 신규 규칙·보관·인증 경계 시험 | 57건 통과 |
| 검색·부서·반복·서식 업무 계층 합성 통합시험 | 21건 통과 |
| 배포 검사기·도구 입력 계약 시험 | 12건 통과 |
| 실제 MCP SDK 전체 pytest | 수집 단계 중단: SDK 없음. 4개 import 오류 |
| 실제 stdio/HTTP MCP 프로토콜 | SDK 없음으로 시작 못함 |
| OAuth 인증서버와 ChatGPT 실제 로그인 | 미실시 |
| CLIK·서구 홈페이지 현재 실조회 | 미실시 |
| GitHub·Render 원격 변경 및 배포 | 수행하지 않음 |

시험에 사용한 HTTP는 MockTransport 또는 ASGI 합성 요청입니다. 실제 서버 인증을 통과했다는 뜻이 아닙니다.
최종 선택 시험 로그에는 Python 3.13의 멀티스레드 환경에서 fork 사용과 관련한 DeprecationWarning 4건이 있습니다.
해당 기존 동시성 시험은 통과했지만 이 경고를 숨기지 않았습니다. CI는 Python 3.11·3.12에서 실제 SDK와 다시 검사하도록 구성했습니다.

## 2. 수정 내용과 확인 사례

### 부서 이력 적용

이전에는 과거 부서명이 검색에만 반영되고 최종 답변자 분류에서 빠질 수 있었습니다.
이제 별칭·적용기간을 검색, 부서별 분류, 반복 분석, 후속조치 후보 및 서식 작성에 공통 사용합니다.
합성 조직이력에서 이전 이름으로 된 답변이 최종 분류되는 사례와 적용기간 밖·날짜 미상 사례를 검사했습니다.
이력의 basis를 필수로 받지만 그 서류의 진위를 검증한 것으로 표시하지는 않습니다.

### 반복 주제어와 요구의 방향 구분

‘매장 확대 검토’와 ‘매장 확대 보류’를 서로 다른 합성 회의에 넣어 검사했습니다.
같은 주제어가 반복되되 `same_request_confirmed=false`와 상반된 문면 단서가 반환됩니다.
동일 방향처럼 보이는 문장도 자동으로 동일 요구로 승인하지 않습니다.
표시 상한 때문에 후보나 인용을 생략하면 생략 건수·스냅샷 근거 회수 방법을 표시합니다.

### 조회 상태와 기간

PARTIAL+0건은 PARTIAL, 모든 출처 실패는 ERROR, 정상 조회 범위의 0건은 EMPTY가 유지되는지 검사했습니다.
일부 연도 오류와 정상 빈 연도가 섞이면 PARTIAL입니다. 스냅샷을 읽지 못한 경우도 별도로 표시합니다.
2026-09-21 기준 rolling 2년이 2024-09-21~2026-09-21로 나뉘는지, 달력연도 조회와 다른지,
윤년·잘못된 날짜·미래 기준일·과도한 조회범위가 올바르게 처리되는지 검사했습니다.

### 근거·서식 연결

원문 답변의 발언 위치와 출처 필드를 보존합니다. 다른 회의의 동일한 약속은 별개로 남깁니다.
잘못된 event_id가 일부 섞인 선택은 전체를 거부합니다. 후속조치는 선택된 질의의 연결 범위로 제한합니다.
이행완료·현재 실적·정책 판단을 자동 작성하지 않는 기존 원칙을 유지했습니다.

### 인증·용량·보관

정적 Bearer와 OAuth 토큰 검증 모드를 분리했습니다. 외부 `local` 모드는 시작하지 못하게 했습니다.
OAuth는 외부 인증서버의 introspection을 이용합니다. issuer·audience·만료·scope·subject 오류,
철회된 토큰 재검사, 인증서버 장애 거부, 토큰 리디렉션 금지 등을 합성 응답으로 검사했습니다.
사용자별 스냅샷 조회가 분리되고 전체 저장 상한은 유지되는지, 한글이 실제 UTF-8 바이트로 계산되는지 검사했습니다.

### 배포 확인

`council_status`가 버전·실행 파일 지문·manifest 대조를 제공하도록 확장했습니다.
검사기는 버전이 같아도 도구 인자가 다르면 MISMATCH를 반환하고, healthz가 성공해도 MCP 401이면 인증 실패로 표시합니다.
이 시험은 합성 HTTP 응답입니다. 실제 배포 서버를 확인한 결과가 아닙니다.

## 3. 로그와 재실행 방법

최종 결과: `docs/verification/v240/final-local-suite.log`, `final-local-suite.xml`.
환경: `environment.json`. 시험 범위: `verification-summary.json`.
전체 SDK 시험 중단 기록: `full-sdk-suite-attempt.log`, `protocol-attempt.log`.
설치 시도: `dependency-install-attempt.log`.

```bash
python -m pytest -q tests/test_evidence_v2.py tests/test_workflows.py tests/test_sources.py tests/test_response_budget.py tests/test_security.py tests/test_upgrade24.py tests/test_service24_offline.py tests/test_release24.py -k "not actual_sdk"
```

SDK를 설치할 수 있는 환경에서는 제외 없이 다음을 추가 실행합니다.

```bash
python -m pip install -r requirements.txt pytest==8.4.2
python -m pytest -q
python tests/protocol_smoke.py
python scripts/export_runtime_schemas.py > runtime-tool-schemas.json
```

설치 로그의 ‘No matching distribution’은 앞선 DNS 실패 때문에 조회하지 못한 결과입니다.
해당 버전이 존재하지 않는다거나 소스가 잘못됐다는 의미로 해석하지 않았습니다.
`docs/source-tool-contracts.json`은 AST 분석 결과이며 실제 SDK가 생성한 명세와 구분합니다.
과거 제작자의 시험 기록은 historical-v231 폴더로 분리했고 이번 통과 건수에 합산하지 않았습니다.

## 4. 운영 전 완료 기준

실제 SDK 전체 시험 통과, 인증서버/ChatGPT 로그인 성공, 사용자별 접근 검수, 배포 코드 지문 일치,
최신 tools/list 갱신, CLIK/홈페이지 읽기 성공, 기준 회의록의 질의·답변 원문 대조가 필요합니다.
공식 의회 자료를 충분히 확인하지 않은 상태에서 검색 정확도·속도·누락률이 개선됐다는 수치는 제시하지 않았습니다.
기존 의회 명칭·코드 데이터는 제공본을 승계했으며 현행 조직명이나 모든 수집 경로를 실시간 검증하지 않았습니다.

외부 OAuth 인증서버 구축, 자동 로그인 성공, 전체 회의록 전수수집, 취약점 부재, 운영 부하 안정성을 이 보고서가 보증하지 않습니다.

## 5. 설계 근거 공식 문서

- OpenAI 인증: https://developers.openai.com/apps-sdk/build/auth/
- MCP 인증: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- 토큰 introspection: https://datatracker.ietf.org/doc/html/rfc7662
- Render 새 코드 배포: https://render.com/docs/deploys

위 문서는 설계 방향을 확인하는 자료이며 실제 서비스 연결 성공의 증거와 다릅니다.
