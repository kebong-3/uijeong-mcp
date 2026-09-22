# 의정소통 MCP 2.5.0-rc.1

공무원의 지방의회 답변 준비를 돕는 근거 중심 MCP 서버입니다. 사용자 제공 2.4.0-rc.1을 바탕으로 개선했습니다.

**새 기본 업무 흐름:** 사업·기간 지정 → 과거 질의답변 수집 → 현재 자료 연결 → 답변 초안 작성 → 문장별 근거 점검 → 회의 후 증빙 검토.

서버는 회의록과 검토 도구를 제공하고, 연결된 AI가 이 근거로 문장을 작성합니다. 별도의 생성형 AI API 키를 요구하지 않습니다. CLIK 전국 검색에는 기존 CLIK 키가 필요합니다.

## 먼저 읽을 파일

- [사용·교체 안내](docs/UPGRADE_v250_KO.md)
- [기능·설계·검증보고서](docs/VERIFICATION_v250_KO.md)
- [공식 자료 조사와 반영](docs/RESEARCH_v250_KO.md)
- [복사해서 쓰는 요청 예시](docs/EXAMPLES_v250_KO.md)
- [합성자료 실행 예시](docs/examples-v250/실행예시_합성자료.md)

## 이번에 추가한 기능

| 도구 | 업무에 주는 도움 |
|---|---|
| `council_prepare_response` | 기간을 명시해 검색하고, 인용ID·과거 문답·제공 현황·준비질문·확인사항·보고서형 본문을 함께 반환 |
| `council_audit_claims` | 문장별 발췌·초안 위치·숫자·조건 표현을 대조하고, 숫자가 없는 미연결 주장도 찾음 |
| `council_compare_metrics` | 사업·대상·기간·회계기준을 대조한 후 금액 단위를 환산. 기준 불일치 시 계산 보류 |
| `council_compare_evidence` | 여러 회의의 발언을 정확한 원문과 위치를 보존해 나란히 비교 |

기존 부서별 정리, 반복 주제어, 후속조치 검토, 기관 서식 기능은 유지합니다. 새 프롬프트 `근거기반_의회답변`과 안내 리소스 2개도 제공합니다.

## 실행

Python 3.11 이상을 사용합니다. 이번 실행 검증은 Python 3.12와 실제 MCP SDK 1.30.0으로 했습니다.

```bash
python -m pip install -r requirements.txt
python uijeong_mcp.py
```

HTTP 운영은 인증·허용 도메인을 설정한 뒤 실행합니다. 기존 `render.yaml`, `render.oauth.yaml`을 지원합니다. 상세 설정은 교체 안내에 있습니다.

```bash
python scripts/check_config.py --http --manifest
python uijeong_mcp.py --http
```

| 프로필 | 도구 수 | 용도 |
|---|---:|---|
| core | 5 | 검색·원문 확인 중심, 신규 업무도구 미노출 |
| work | 18 | 공무원 답변 준비 권장 |
| lite | 26 | 기존 호환 검색 도구까지 사용 |
| full | 38 | 전체 도구·개발 검수 |

`UIJEONG_PROFILE=work`를 권장합니다. 버전 문자열이나 개수만 보지 말고 `council_status(live=False)`의 코드 지문과 manifest 일치를 함께 확인합니다.

## 검증 재실행

```bash
python -m pip install pytest==8.4.2
python -m pytest -q
python tests/protocol_smoke.py
python tests/regression_r0.py
python tests/offline_check.py
python scripts/demo_response25.py
```

`docs/verification/v250/`에 이번 로그를 보관합니다. 이전 버전 로그는 이번 통과 수에 더하지 않습니다. CI는 Python 3.11/3.12에서 실제 SDK로 재실행하도록 구성했습니다.

## 정확한 사용 범위

- 원문·문자열·숫자 대조는 **의미상 입증 또는 최종 제출 승인과 다릅니다.** `ready_for_submission`은 자동 승인하지 않습니다.
- 과거 발언, 담당자 제공 현황, 준비 제안을 구분합니다. 제공 문서는 서버가 직접 열람한 것이 아닙니다.
- `PARTIAL`과 `ERROR`를 자료 없음으로 바꾸지 않습니다. 이어보기·미열람 회의·조회 오류를 확인합니다.
- 공개 회의록만 사용자 범위별 SQLite 스냅샷에 보관합니다. 초안·현황자료 입력은 서버에 저장하지 않습니다. 이용 클라이언트의 보관 정책은 별도입니다.
- 전국 회의록은 CLIK, 홈페이지 직접 수집 어댑터는 서구의회입니다. 전국 모든 홈페이지 자동수집·현재 법령 검증·PDF/HWP 자동 분석까지 구현한 것은 아닙니다.
- 새 패키지는 운영 전 검수용 후보판입니다. GitHub·Render 배포와 ChatGPT 실제 로그인은 이번에 수행하지 않았습니다.
