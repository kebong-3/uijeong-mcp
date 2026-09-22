# 지방의회 MCP 연결 복구 (2026-09-22)

버전: 2.5.0-rc.2. 기존 도구 기능은 유지합니다.

## 변경 사항
- 최상위에 잘못 올라간 Python 파일 24개 정리. 동일본 21개는 정상 폴더에 보존, 다른 내용 3개는 docs/history/upload-recovery-20260922에 이동.
- Uvicorn 로그의 필수 5개 인자를 보존하면서 인증키·토큰·인가코드를 마스킹.
- 관리자 로그인·명시적 연결 승인·S256 PKCE를 사용하는 단일 관리자 OAuth 모드 추가.
- 무인증 도구 접근은 계속 거절. CLIK API 키는 변경하지 않음.
- 배포 파일 무결성 검사를 유지하고 수정 내용에 맞게 명세 갱신.

## 운영 설정
UIJEONG_AUTH_MODE=oauth_local
UIJEONG_RESOURCE_URL=https://uijeong-mcp.onrender.com/mcp
UIJEONG_OAUTH_ADMIN_PASSWORD_HASH에는 scrypt 해시를 설정합니다. 평문 비밀번호는 저장소에 넣지 않습니다.
기존 UIJEONG_BEARER_TOKEN은 서명키를 도출하는 용도로만 보존되며, 이 모드에서 고정 Bearer 직접 로그인은 거절합니다.

## 보안 및 범위
단일 관리자 비공개 시범 운영용입니다. 기관 전체 사용자는 기존 외부 OAuth 모드와 기관의 검증된 계정/SSO를 연결하고 보안 검토를 받아야 합니다.
인가코드 60초·1회 사용, 접근 토큰 1시간, 갱신 토큰 7일·회전·재사용 시 토큰 묶음 폐기. 비밀번호·토큰 평문을 SQLite에 저장하지 않습니다.
승인 화면은 비밀번호·보안 쿠키·CSRF·동일 출처를 검증합니다. 허용된 ChatGPT 반환 주소만 사용합니다.
기관 보안 승인이나 실제 ChatGPT 사용자 승인 완료를 이 코드만으로 보장하지 않습니다.
무료 인스턴스의 비영구 저장장치와 절전 정책은 변경하지 않았고 유료 자원을 만들지 않습니다. 재배포로 토큰 DB가 사라지면 재로그인이 필요합니다.

## 연결
ChatGPT에서 기존 /mcp 주소를 OAuth 방식으로 재연결합니다. 승인 화면에는 이 서버의 관리자 연결 비밀번호를 입력합니다. CLIK API 키나 ChatGPT 계정 비밀번호가 아닙니다.

## 검증
tests/test_connection_repair.py는 합성 정보로 인증·로그 회귀시험을 수행합니다.
GitHub Actions에서 실제 라이브러리를 설치하고 전체 pytest, stdio, Streamable HTTP를 검사합니다. 결과는 해당 워크플로와 아티팩트를 확인하세요.
