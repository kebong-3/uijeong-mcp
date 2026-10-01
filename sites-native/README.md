# 지방의회·예산·조례 · ChatGPT Sites 네이티브 서버

ChatGPT Sites의 Cloudflare Workers에서 14개 MCP 도구를 직접 실행합니다. Render에 조회를 위임하지 않습니다. 기존 Render 운영 서버와 GitHub main은 fallback으로 보존합니다.

## 출처

- `kebong-3/uijeong-mcp` / `chatgpt-sites`: `uijeong_mcp.py` 의회 코드표, `budget_mcp/api_catalog.json` 공식 API 정의, `jachi/client.py` 법제처 API 요청 형태
- `chatgpt-sites-migration-pack.zip`: 화면 구성, 정책, 확인 수준과 통합 검토 지침
- 브랜치의 기존 `tool-schemas.json`은 34개 도구이며 Render의 현행 40개 도구와 일치하지 않습니다. `branch-tool-schemas.json`, `tool-catalog.json`은 비교 기록입니다. 새 서버의 실제 14개 도구는 `/mcp` tools/list로 확인합니다.

## 실행 환경

`.openai/hosting.json`에 Sites 프로젝트 ID와 `mcp` capability가 있습니다. 공식 키는 Sites runtime secret으로 설정하며 소스에 쓰지 않습니다.

필요 인증값: `CLIK_API_KEY`, `LAW_OC`, `LOFIN_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `KOSIS_API_KEY`.

현 단계에서 Render 비밀값 읽기를 지원하는 연결 도구가 없어 키 이전은 미완료입니다. 공식 API 호출은 NOT_CONFIGURED를 반환합니다. 키가 없는 상태를 실제 조회 성공으로 표시하지 않습니다.

## 검증

`node tests/mcp.test.mjs`: 26개 검증(프로토콜, 6개 화면, 인증 차단, 큰 금액 정확성, 재원검산, 미설정 오류, 공식 API 어댑터 모의 응답, 비밀값 비노출). 인증된 공식 API 실조회는 아직 미실시입니다.

`bash scripts/build.sh`와 `node scripts/validate-artifact.mjs`: ESM Worker 배포 형식 확인.

## 기능 범위

현재는 핵심 조회·계산 도구 14개입니다. Render의 40개 도구 전부를 이식하지 않았습니다. 상세 질의답변 묶음, 반복쟁점/회기 준비, 조례 개정문 생성 등은 기존 Render 플러그인을 통해 사용합니다. 서버 조회 오류와 결과 없음은 구분합니다. 원문 구간은 API 원시문서 슬라이스로 반환하며 발언자 정규화·쪽수 재구성은 하지 않습니다.

새 Sites 플러그인의 설치/계정 연결은 사용자가 ChatGPT 설치 UI에서 완료해야 합니다. 게시나 플러그인 ID 생성이 설치 완료를 의미하지 않습니다.
