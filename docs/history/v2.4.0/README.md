# 의정소통 MCP 2.4.0-rc.1

광주 서구를 기본 조회 대상으로 삼는 지방의회 근거 수집·부서별 답변 준비 서버입니다.
사용자 제공 **2.3.1 소스의 개선 후보판**입니다. 원격 서비스가 자동 갱신되는 파일은 아닙니다.

**구현·로컬 검증 완료 / 실제 MCP SDK 통신·OAuth 로그인·CLIK 실조회·Render 배포는 이번 제작 환경에서 미검증.**
`rc.1`은 이 구분을 위한 표기입니다. CI와 실제 연결 검수를 통과한 후 운영에 적용하세요.

## 바뀐 내용

| 분야 | 2.4.0-rc.1 |
|---|---|
| 부서 이력 | 과거 부서명과 적용기간을 검색·최종 분류·후속조치·서식에 동일 적용. 이력 출처는 사용자 제공으로 표시 |
| 반복 논의 | 반복 **주제어 후보**로 명시. 확대/보류 등 상반된 문면 단서를 함께 표시하며 같은 요구를 자동 확정하지 않음 |
| 조회 상태 | 일부 조회·실패와 정상 0건을 구분. 빈 결과 때문에 PARTIAL/ERROR를 EMPTY로 바꾸지 않음 |
| 기간 | rolling_years, calendar_years, 명시 날짜를 구분. 한국시간 기준·양 끝 날짜 포함 |
| 근거 연결 | 답변의 발언번호·위치·출처 보존. 다른 회의의 동일 문구 약속을 합치지 않음. 선택하지 않은 질의의 후속조치 혼입 방지 |
| 보관 | 요청 인증 주체별 스냅샷 분리, 전체 보관 한도 유지, UTF-8 바이트 기준 용량 계산 |
| 인증 | 기존 정적 Bearer 유지 + 별도 인증서버의 OAuth 토큰을 검증하는 리소스 서버 모드 추가 |
| 배포 확인 | 최소 healthz, 실제 코드 해시·도구 인자 대조, 비밀값 없는 설정 점검 |

## 먼저 읽을 자료

- [교체·배포 안내](docs/UPGRADE_v240_KO.md)
- [검증 결과와 남은 검수](docs/VERIFICATION_v240_KO.md)
- [인증 및 보안 경계](docs/SECURITY_v240_KO.md)
- [실무 호출 예시](docs/EXAMPLES_v240_KO.md)
- [변경 이력](CHANGELOG.md)

## 설치·로컬 실행

Python 3.11 또는 3.12와 인터넷 연결이 가능한 개발 환경에서 다음을 실행합니다.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/check_config.py --http --manifest
python uijeong_mcp.py --http
```

기본은 루프백 로컬 HTTP입니다. 외부 공개 시 인증과 허용 호스트를 반드시 설정합니다.
stdio로 연결할 때는 `python uijeong_mcp.py`를 사용합니다. CLIK 조회에는 별도의 `CLIK_API_KEY`가 필요합니다.
**`.env.example`은 참고용입니다. `.env` 파일만 만들면 자동으로 환경변수를 읽는 구조가 아닙니다.**
Render 환경변수 화면, 운영체제 환경변수 또는 승인된 실행 도구로 설정하세요.
키를 소스·명령행 인수·대화에 입력하거나 공개 저장소에 올리지 마세요.

## 인증 방식

`UIJEONG_AUTH_MODE=bearer`는 정적 Authorization 헤더를 전달하는 클라이언트/게이트웨이용입니다.
`oauth`는 OAuth 인증서버가 발급한 액세스 토큰을 RFC 7662 introspection으로 검증합니다.
**이 패키지는 로그인 화면·인증코드 발급·PKCE·클라이언트 등록을 제공하는 인증서버가 아닙니다.**
ChatGPT 직접 OAuth 연결에는 호환되는 외부 인증서버 설정과 실제 로그인 시험이 별도로 필요합니다.
인증을 제거해 연결을 통과시키지 않도록 외부 `local` 모드는 시작 단계에서 차단합니다.

## 도구 프로필

`core` 5개, `work` 14개, `lite` 22개, `full` 34개입니다. 기본 Render 템플릿은 `work`입니다.
부서 분석은 `work` 이상을 사용하세요. 도구 수가 많아진 것이 이번 개선의 목적은 아닙니다.
도구 개수만으로 배포 버전을 판정하지 마세요.
`docs/source-tool-contracts.json`은 **소스 AST로 만든 입력 계약**이며 실제 SDK 실행 결과가 아닙니다.
실제 SDK 명세는 설치 후 다음과 같이 새로 내보냅니다.

```bash
python scripts/export_runtime_schemas.py > runtime-tool-schemas.json
```

## 시험

```bash
python -m pip install pytest==8.4.2
python -m pytest -q
python tests/protocol_smoke.py
```

위 전체 명령은 실제 mcp SDK를 요구합니다. 이번 제작 환경에서 SDK 다운로드가 막혀 실행하지 못한 시험을 통과로 표시하지 않았습니다.
독립 실행 시험과 업무 계층 합성 통합시험의 실제 결과는 검증보고서와 JUnit 로그에 있습니다.
GitHub Actions는 실제 SDK 설치, 전체 회귀시험, stdio/HTTP 프로토콜 검사를 실행하도록 유지·보강했습니다.

## 운영 판단의 한계

자료 수집은 출처별·페이지별 상한이 있는 조회입니다. COMPLETE도 전국 또는 해당 의회 전체 전수조사를 의미하지 않습니다.
회의일과 회계연도, 이용자 누계와 실인원, 검토 답변과 이행 완료를 자동으로 같은 것으로 취급하지 않습니다.
의원 개인 성향·역량 평가·순위·선거 예측을 제공하지 않습니다.
기존 의회 코드·명칭·출처 목록은 2.3.1 제공자료를 승계했으며 이번에 최신 명칭을 실조회 검증한 것은 아닙니다.

과거 제작자의 2.3.1 보고서·명세는 `docs/history/v2.3.1`, 과거 시험 기록은 `docs/verification/historical-v231`에 분리했습니다.
