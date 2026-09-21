# 2.5.0 추가 인수인계

현재 진입 문서는 README.md와 docs/UPGRADE_v250_KO.md입니다. response_core.py는 순수 검토 로직, response_tools.py는 스냅샷·공개 수집과 도구 등록, response_guidance.py는 프롬프트·리소스를 담당합니다. 신규 도구는 work/lite/full에 4개 추가했습니다. 이전 서명·인증·DB 구조는 유지합니다. 예시 재생성: python scripts/demo_response25.py. 최종 검증은 docs/verification/v250/를 보세요. 아래는 이전 버전 인수인계 기록입니다.

---

# 개발자 인수인계

## 우선 검수

1. 실제 mcp==1.30.0 환경에서 전체 pytest 및 tests/protocol_smoke.py 실행. 이번 제작환경은 SDK 다운로드 DNS 실패로 실행 못함.
2. OAuth 도입 시 별도 인증서버의 실제 introspection 응답이 본 구현의 필수 iss/aud/exp/sub/scope 계약을 충족하는지 확인.
3. 승인된 ChatGPT OAuth 등록 방식·PKCE·콜백과 사용자 정책은 외부 AS에서 설정. 이 소스는 AS가 아닌 리소스 서버임.
4. 개발용 Render 배포, verify_deployment.py 코드 지문 대조, 최신 도구 명세 등록 후 실제 원문 검수.

## 변경 모듈

period_core: KST·명시기간·rolling/달력연도 처리.
department_aliases + dept_core: 사용자 제공 별칭과 적용기간을 모든 분류에 적용.
recurrence_core: 요구 문면 단서만 반환. 의미 일치/반복 요구 확정 금지.
coverage_core + service_v2: 오류·부분조회·빈 결과 분리 및 근거 보관·회수.
runtime_security + oauth_resource: 외부 AS introspection, 요청별 scope, 바이트 기준 보관 상한.
result_contract: SDK 객체 변환을 호출 시점으로 늦춰 업무 계층 독립 시험 가능.
term_core: 기존 주제어 추출 함수를 독립 모듈로 이동.
release_info + scripts: 단일 버전·지문·manifest·로컬/원격 검증.

## 회귀시험 성격

신규 업무 통합시험은 실제 service_v2 함수들을 합성 upstream에 연결한다. MCP SDK를 흉내 내 통과한 프로토콜 시험이 아니다.
원격 검증 스크립트 시험 또한 합성 HTTP를 사용하며 실제 배포 성공 기록으로 사용하지 않는다.
GitHub CI는 실제 SDK 없이는 실패하게 유지했다. SDK 부재를 자동 skip으로 바꿔 성공으로 처리하지 말 것.

## 릴리스 작업

코드 변경 후 tests 실행 → python scripts/build_manifest.py → python scripts/check_config.py --manifest.
manifest는 자기 자신을 해시하지 않는다. runtime_sha256은 서버 루트 파이썬·data JSON·requirements를 포함한다.
files_sha256은 배포 자료 전체 검사이며 서명/제작자 신원 인증이 아니다.
source-tool-contracts는 AST 원본 계약, export_runtime_schemas는 실제 설치된 SDK 결과로 구분.
런타임 파일을 하나라도 바꾸면 manifest를 다시 만들고 전체 파일을 같은 커밋으로 배포할 것.

## 범위 밖

일반 JWT/JWKS 토큰 검증(이번은 introspection), 외부 AS 자체구축, 멀티레플리카 전역 속도제한,
최신 의회명 데이터 검수·전국 크롤러 확대, 실제 정책 이행 자동판정은 이번에 구현/검증하지 않음.
