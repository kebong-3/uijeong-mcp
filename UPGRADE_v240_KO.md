# 2.3.1 → 2.4.0-rc.1 교체 안내

## 1. 지금 제공된 것과 아직 필요한 것

제공: 수정 소스 전체, 신규 회귀시험, 합성 업무 통합시험, 인증 리소스 서버, 설정·배포 대조 스크립트, CI.
별도 필요: 실제 SDK 설치 후 전체 테스트, 외부 인증서버 설정, ChatGPT 로그인, CLIK/홈페이지 실조회, 운영 배포.
현재 연결된 MCP나 GitHub 저장소는 이 파일을 만드는 과정에서 수정하지 않았습니다.

## 2. 기존 서비스 백업 후 개발용 배포에서 검수

기존 커밋을 기록하고 환경변수 이름과 운영 저장소를 안전한 관리 경로에 백업합니다. 키 값을 대화에 붙여 넣지 않습니다.
ZIP의 `uijeong-mcp` 폴더 **안의 파일 전체**를 GitHub 프로젝트 루트에 반영합니다.
`uijeong_mcp.py` 한 개만 바꾸면 새 모듈을 찾지 못합니다. `scripts`, `tests`, `data`, `docs`, `.github`와 설정파일도 함께 넣습니다.
기존 `.env`, 실제 키, `state/*.sqlite3`를 GitHub에 올리지 않습니다.

`requirements.txt`의 MCP 1.x 버전은 2.3.1과 동일하게 유지했습니다. 이번에는 검증되지 않은 SDK 주요 버전 변경까지 함께 하지 않았습니다.
설치가 가능한 개발 환경에서 `pip install -r requirements.txt pytest==8.4.2`, `python -m pytest -q`, `python tests/protocol_smoke.py`를 실행합니다.
이 단계가 실패하면 원인을 해소하기 전 운영 버전을 바꾸지 않습니다. 시험을 삭제하거나 결과를 통과로 덮지 않습니다.

## 3. 인증 방식은 둘 중 하나만 선택

### A. 현재 연결 계층이 정적 Bearer를 전달하는 경우

기존 토큰을 계속 사용할 수 있습니다. 새 비밀값을 소스에 만들지 않습니다.

| Render 환경변수 | 설정 |
|---|---|
| UIJEONG_PROFILE | work |
| UIJEONG_AUTH_MODE | bearer |
| UIJEONG_BIND_HOST | 0.0.0.0 |
| UIJEONG_ALLOWED_HOSTS | 실제 서비스 도메인만. https://와 /mcp를 붙이지 않음 |
| UIJEONG_BEARER_TOKEN | 기존 안전한 32자 이상 토큰 또는 비밀관리 도구에서 발급한 값 |
| CLIK_API_KEY | 기존 CLIK 키. MCP 접속 인증 토큰과 별개 |

`render.yaml`은 이 방식의 호환용입니다. **ChatGPT가 정적 토큰을 자동으로 보내 준다는 뜻은 아닙니다.**
현재 401의 원인이 헤더 전달 불가라면 코드 교체만으로 해결되지 않습니다.

### B. ChatGPT 직접 OAuth 연결을 구성하는 경우

`render.oauth.yaml`을 참고하되 외부 인증서버를 먼저 구성해야 합니다. 이 템플릿은 인증서버를 만들어 주지 않습니다.
서버는 외부 인증서버의 HTTPS introspection endpoint에 client_secret_basic 방식으로 토큰을 확인합니다.
인증서버는 authorization-code + PKCE S256, 승인된 클라이언트 등록 방식, 실제 ChatGPT 관리 화면에서 안내하는 콜백을 지원해야 합니다.
콜백 URL이나 issuer 주소를 추정해서 입력하지 마세요.

| 환경변수 | 의미 |
|---|---|
| UIJEONG_AUTH_MODE | oauth |
| UIJEONG_RESOURCE_URL | 실제 https://서비스도메인/mcp. 토큰 aud와 정확히 일치 |
| UIJEONG_OAUTH_ISSUER | 인증서버 issuer. introspection iss와 정확히 일치 |
| UIJEONG_OAUTH_INTROSPECTION_URL | 관리자가 확인한 실제 HTTPS 토큰 검증 endpoint |
| UIJEONG_OAUTH_CLIENT_ID / CLIENT_SECRET | MCP 리소스 서버가 introspection을 호출할 자격정보 |
| UIJEONG_OAUTH_SCOPES | 기본 예 council:read. 인증서버가 실제로 발급하는 scope와 일치 |
| UIJEONG_OAUTH_CACHE_SECONDS | 기본 0. 최대 15, 캐시 사용 시 해당 시간의 취소 반영 지연 가능 |
| UIJEONG_OAUTH_ALLOWED_SUBJECTS | 선택. 허용할 실제 sub 목록, 쉼표 구분. 미설정 시 올바른 scope를 가진 해당 issuer 사용자 전체 허용 |

**이 모드에서는 기존 UIJEONG_BEARER_TOKEN을 Render 환경변수에서 제거합니다.** 둘을 동시에 두면 안전을 위해 시작하지 않습니다.
CLIK_API_KEY는 삭제할 대상이 아닙니다. 인트로스펙션 자격정보와 ChatGPT OAuth 클라이언트 자격정보도 용도가 다릅니다.
응답에 `active`, `iss`, `aud`, `exp`, `sub`, `scope`가 없거나 맞지 않으면 인증을 거부합니다.
사용하려는 인증서버가 이러한 introspection 응답을 지원하는지 먼저 확인하세요. JWT만 제공하고 introspection이 없는 환경은 이 구현과 바로 호환되지 않습니다.

## 4. 배포 후 4단계 확인

첫째, Render에서 새 커밋을 배포합니다. 단순 Restart는 새 커밋 배포와 다릅니다.
둘째, `/healthz`는 프로세스 응답 확인에만 사용합니다. 200이어도 로그인·CLIK 검증은 끝나지 않았습니다.
셋째, 승인된 관리 환경에서 접속 토큰을 환경변수 `UIJEONG_VERIFY_TOKEN`에 안전하게 설정한 뒤 실행합니다.

```bash
python scripts/verify_deployment.py --url https://YOUR-SERVICE.onrender.com/mcp
```

실제 주소로 변경하세요. 토큰을 `--token`이나 URL에 붙이는 옵션은 제공하지 않습니다.
이 명령은 initialize, tools/list, council_status를 읽고 버전·코드 지문·도구 이름·입력항목을 대조합니다.
OAuth일 때도 이 스크립트는 로그인·토큰 발급을 대신하지 않습니다. 기존 승인된 인증 흐름으로 받은 토큰으로 진단합니다.
401/403이면 MCP 인증부터 확인하고, 코드 지문 불일치면 다른 배포·부분 교체·구버전 연결을 확인합니다.
넷째, ChatGPT 앱/연결에서 도구 정의를 새로 가져온 뒤 새 대화에서 상태·조회 시험을 합니다.

```text
council_status(live=False)
  version = 2.4.0-rc.1
  release_verification.status = MATCH
  profile = work, tool_count = 14 (work 선택 시)
  runtime_fingerprint = 로컬 release_manifest.json 값과 일치
```

`council_status(live=True)`는 CLIK 및 서구 홈페이지 읽기를 실제로 시도하므로 그 단계에서 결과를 따로 확인합니다.

## 5. 실무 자료로 마지막 검수

천원국시의 기간을 2024-09-21~2026-09-21로 명시해 검색합니다. 날짜는 검수 기준 예시입니다.
확인된 회의록 몇 건을 기준으로 질의자·답변자·발언 내용·회의일·출처를 사람이 대조합니다.
coverage에 미조회 페이지가 남으면 source_offset, site_start_page, pending_refs로 이어서 확인합니다.
기부금 사용연도, 운영실적 집계기준, 후속조치 이행은 회의록 답변만으로 확정하지 않습니다.

## 6. 저장소·복구

UIJEONG_STATE_DB를 영속 경로에 두지 않으면 재배포 후 근거 스냅샷을 다시 수집해야 할 수 있습니다.
기존 SQLite 테이블 구조는 유지하지만 새 HTTP 요청 범위와 맞지 않는 과거 스냅샷은 다시 조회합니다.
문제 발생 시 기록한 이전 커밋과 인증방식으로 되돌립니다. OAuth/Bearer 전환 때 해당 환경변수도 함께 대조하세요.
기존 스냅샷을 억지로 다른 사용자 범위에 붙이는 복구 방식은 사용하지 않습니다.

## 참고 공식 문서 (2026-09-21 확인)

- OpenAI Auth: https://developers.openai.com/apps-sdk/build/auth/
- OpenAI Developer mode: https://developers.openai.com/api/docs/guides/developer-mode
- MCP authorization: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- RFC 7662: https://datatracker.ietf.org/doc/html/rfc7662
- Render deploys: https://render.com/docs/deploys

위 문서는 연결 방식의 근거이며 이 프로젝트가 원격에서 검증됐다는 증거는 아닙니다.
