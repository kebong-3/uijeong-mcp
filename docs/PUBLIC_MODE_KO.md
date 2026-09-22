# 인증 없는 공개 회의록 조회 모드 — 2.5.1-public.1

이 변경은 서버 소유자가 공개 이용·자원 사용을 승인한 배포를 위한 것입니다.
ChatGPT 연결은 인증 없음, URL은 기존 /mcp를 그대로 사용합니다.
서버에서 UIJEONG_AUTH_MODE=public 및 UIJEONG_PUBLIC_READONLY=true를 함께 지정합니다.
none은 public의 별칭입니다. auto 모드에서 인증이 자동 해제되지는 않습니다.

## 기능과 제한

공개 도구 10개: council_find_council, council_evidence_bundle, council_evidence_search,
council_read_source, council_open_record, council_get_evidence, council_data_sources,
council_search_minutes, council_prepare_pack, council_status.

로컬 보관함 조회, 붙여넣기 원문 분석, 내부 초안 입력 도구와 파일 리소스는 등록하지 않습니다.
목록만 숨기는 것이 아니라 실제 호출 대상에서 제외합니다.
공개 검색어와 공개 회의록만 입력해야 합니다. 검색 결과 보관함은 사용자별 비공개 공간이 아닙니다.
공개 자료 임시 저장은 public-readonly-v1 요청 범위로 분리하여 기존 인증/로컬 범위와 섞이지 않습니다.

동시 HTTP 처리 3개, 전체 공유 분당 120개, 요청 본문 64 KiB, 개별 도구 60초 제한입니다.
상세 회의록은 출처·검색어별 최대 6개입니다. 여러 출처·추가 검색어는 각각 호출을 사용합니다.
호환 검색의 depth='깊게'는 허용하지 않으며 '보통' 또는 범위를 좁힌 구조화 검색을 사용합니다.
한도 초과 시 건수 제한 오류 또는 429/503이 발생할 수 있습니다. 사용자별 한도는 아닙니다.
3개의 동시 요청 제한은 3명만 사용 가능하다는 뜻이 아닙니다.
이 설정은 부하 시험 결과나 20명 동시 사용 보장이 아닙니다.

## 보안·운영

CLIK_API_KEY는 변경하거나 클라이언트로 전달하지 않습니다. 응답의 알려진 비밀값도 마스킹합니다.
정확한 Host/Origin 검증, 기존 공식 도메인 제한, TLS 검증, 일일 API 예산, 응답 길이 제한을 유지합니다.
API 이용 한도와 Render 자원을 누구나 소비할 수 있습니다. 로그와 이용량은 운영자가 확인해야 합니다.
무료 인스턴스의 절전, 임시 디스크 소실, 재배포 시 카운터 초기화는 이 변경으로 해결되지 않습니다.

## 코드 구조

기존 uijeong_mcp.py의 업무 로직은 보존하고 HTTP 실행 분기만 추가했습니다.
runtime_security.py의 기존 네트워크·저장·인증 기능을 유지하면서 명시적인 공개 정책과 요청 제한을 추가했습니다.
public_server.py는 허용된 공개 도구만 별도 FastMCP 서버에 등록합니다.
기존 보호 서버의 전체 기능을 그대로 외부에 노출하지 않습니다.
이전의 bearer/oauth/local 설정은 공개 모드를 선택하지 않은 경우 종전 방식으로 작동합니다.

시작 명령은 기존과 같습니다.
python scripts/check_config.py --http --manifest && python uijeong_mcp.py --http

공개 모드 사전검사는 설치된 실제 SDK로 프로토콜 초기화, 도구목록, 인증 없는 의회명 조회,
비공개 도구 거부, 잘못된 Host/Origin 및 과대 요청 거부를 내부 HTTP 전송으로 확인합니다.
사전검사에서는 국회 API나 외부 홈페이지를 조회하지 않습니다.
실제 외부 조회는 배포 후 council_status(live=True)와 근거검색으로 별도 확인해야 합니다.

/healthz의 200은 서버 생존 확인입니다. /mcp를 브라우저로 열면 POST 안내(405)가 나올 수 있습니다.
정상 MCP 사용 여부는 초기화와 실제 도구 호출로 판단해야 합니다.
ChatGPT 앱 상세에서 새로 고침 후 새 대화에서 사용하세요.

## 이 패키지의 검증 범위

운영 기준은 kebong-3/uijeong-mcp의 5b3e5abb59ed0bd7ba0d88d4a50214931b36479f 커밋입니다.
이번 작업에서 GitHub 저장 요청이 연결 도구에 의해 차단되어 main과 Render 운영 설정을 변경하지 못했습니다.
패키지 작성과 로컬 검증은 운영 배포 완료와 구분해야 합니다.
로컬 환경에는 MCP SDK가 설치되어 있지 않고 의존성 다운로드가 실패하여 실제 SDK 프로토콜 검사는 미실행입니다.
실제 ASGI 보안 미들웨어와 도구 경계의 단위검사는 별도 검증기록을 확인하세요.
실제 SDK 자체검사 8항목은 Render에서 의존성 설치 후 시작 전에 실행하도록 구현했으며,
이번 작업 환경에서는 통과 여부를 확인하지 못했습니다. 실패하면 서버 시작을 중단합니다.

참고 공식 문서(2026-09-22 확인):
- GitHub 파일·폴더 업로드: https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository
- Render 환경변수: https://render.com/docs/configure-environment-variables
- ChatGPT 개발자 모드: https://developers.openai.com/api/docs/guides/developer-mode
