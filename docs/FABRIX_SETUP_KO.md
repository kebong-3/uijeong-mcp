# FabriX AI Lab에서 GitHub 코드를 직접 배포하기

`fabrix_server.py`는 별도 실행 옵션 없이 HTTP 서버를 시작하는 진입 파일입니다.
GitHub의 의회·예산·조례 구현을 FabriX 배포 환경에서 실행하며 Render 주소를 호출하지 않습니다.
Python 3.11 이상(3.12 권장), `requirements.txt` 설치가 필요합니다.

## Repository 연결 화면 입력값

| 항목 | 값 |
|---|---|
| 사용자 인증 방식 | 미사용 — 공개자료 조회 도구 전용 |
| Repository URL | `https://github.com/kebong-3/uijeong-mcp` |
| Branch | `main` |
| Executable File | `./fabrix_server.py` |
| Port Number | `8080` |
| Personal Access Token | 이 저장소를 읽을 수 있는 GitHub 토큰을 FabriX에 직접 입력 |

GitHub 토큰은 저장소를 가져오기 위한 값입니다. 아래 공식 API 키와 다릅니다.
비공개 저장소를 사용한다면 토큰에 해당 저장소 접근권한이 있어야 합니다.
Fine-grained 토큰은 소유자 `kebong-3`, 저장소 `uijeong-mcp`, Contents 읽기 권한으로
먼저 시험합니다. FabriX의 토큰 유형 지원·추가 권한 요구는 해당 환경의 오류 상세로 확인합니다.
토큰과 API 키를 코드·문서·GitHub에 기록하지 않습니다.

## 서버 배포 환경

FabriX의 환경변수/시크릿 설정에 실제 값을 등록합니다. 이 파일은 `.env`를 자동으로 읽지 않습니다.
FabriX 화면에 설정란이 없다면 운영자가 환경변수를 주입해야 합니다.
Render에 저장한 비밀값은 자동으로 넘어오지 않습니다.

| 환경변수 | 값/용도 |
|---|---|
| `CLIK_API_KEY` | 기존 CLIK 키 — 실제 의회 회의록 조회 |
| `LAW_OC` | 기존 국가법령정보 공동활용 OC — 법령·자치법규 조회 |
| `LOFIN_API_KEY` | 기존 지방재정365 키 — 예산 조회 |
| `DATA_GO_KR_SERVICE_KEY`, `KOSIS_API_KEY` | 해당 공공데이터/KOSIS 도구를 사용할 때의 키 |
| `DATA_GO_KR_SEARCH_KEY` | 공공데이터 목록 검색을 사용할 때의 키 |
| `UIJEONG_ALLOWED_HOSTS` | FabriX 게이트웨이가 서버에 전달하는 정확한 Host. 여러 개는 쉼표로 구분. `https://`나 경로 없이 입력하며 포트가 전달되면 `도메인:포트` 포함 |
| `FABRIX_SERVER_URL` | `UIJEONG_ALLOWED_HOSTS`를 생략할 때 사용할 실제 서버 URL. 이 진입 파일이 제공하는 선택 설정이며 FabriX가 자동으로 제공한다고 가정하지 않음 |
| `UIJEONG_ALLOWED_ORIGINS` | 요청에 Origin 헤더가 있을 때 해당 정확한 출처. 예: 실제 FabriX 누리집의 `https://도메인` |
| `PORT` | 기본 `8080`. 바꾸면 화면의 Port Number도 같은 값으로 설정 |
| `UIJEONG_STATE_DB` | 선택: 이어보기용 공개자료 캐시 파일 경로. 기본값은 임시 디렉터리 아래 `uijeong-fabrix/state.sqlite3`. 컨테이너 재생성 시 사라질 수 있음 |

기본값은 `UIJEONG_AUTH_MODE=public`, `UIJEONG_PUBLIC_READONLY=true`,
`UIJEONG_BIND_HOST=0.0.0.0`입니다. 보호 모드를 명시한 환경변수는 임의로 공개 모드로 바꾸지 않고
오류로 알립니다. FabriX 사용자 인증을 **사용**으로 바꾸는 연동은 이 파일의 지원 범위가 아닙니다.

허용 Host를 설정하기 전에는 로컬·컨테이너 호스트만 허용합니다. 임의의 외부 Host를 받지 않습니다.
외부 접속이 403이면 게이트웨이가 전달하는 실제 Host/Origin을 확인하여 위 설정에 등록하세요.
와일드카드나 수신 요청에서 추출한 호스트로 검사 기능을 우회하지 않습니다.

## 실행과 점검

```sh
python -m pip install -r requirements.txt
python fabrix_server.py --check
python fabrix_server.py
```

- MCP 전송: **Streamable HTTP**, 경로 **`/mcp`**
- 상태 확인: **`GET /healthz`**
- 실제 SDK로 MCP 초기화·공개 도구 40개·로컬 도구 호출·보안 경계를 점검함.
- `--check`는 외부 API 키의 유효성, 실제 자료 반환, FabriX 연결 성공을 검증하지 않음.
- API 키가 없어도 서버 시작·도구 목록은 점검할 수 있음. 실제 자료 조회에는 해당 키가 필요함.
- SSE 전용(`/sse`) 클라이언트와는 별도 호환 작업이 필요함. `/mcp`의 단독 GET은 405일 수 있으며,
  MCP POST 초기화/도구목록으로 연결 여부를 판단해야 함.

## 오류 단계별 확인

| 증상 | 확인할 것 |
|---|---|
| 2단계 Repository 연결 실패 | 저장소 URL, `main`, 실행 파일 경로, 토큰 만료·저장소 선택·권한, FabriX의 GitHub 외부 접속 가능 여부. 화면의 일반 오류만으로 원인 확정 불가 |
| 3단계 서버 배포 실패 | Python 버전, `requirements.txt` 설치, 실행 로그, 환경변수, 포트 |
| 서버 기동 후 403 | 실제 Host/Origin과 허용 목록 일치 여부 |
| `/mcp` GET 405 | Streamable HTTP POST 초기화·도구목록 요청으로 확인 |
| 도구 목록은 보이나 자료 조회 실패 | CLIK·법령·예산 키와 각 공식 API의 외부 접속 가능 여부 |

이 변경은 파일 단독 실행 시 HTTP가 시작되지 않던 문제를 해결합니다.
FabriX 로그인 환경에서의 연결 테스트와 배포는 별도로 확인해야 합니다.
