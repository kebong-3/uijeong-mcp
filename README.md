# 지방의회·예산·조례 MCP

전국 지방행정 업무의 회의록 근거, 예산 수치, 조례 근거를 하나의 연결에서 다룹니다.
개발·기획: 서구청 펀온워크 AI혁신분과 에이블(AIBLE).

- 통합 버전: `4.0.0-public.1`
- 직원 연결 주소: `https://uijeong-mcp.onrender.com/mcp`
- 인증: **없음**
- 의회 21개 + 예산 8개 + 조례 9개 + 업무흐름 2개 = 공개 도구 40개
- 공개자료 조회·계산·검토용 초안 생성. 전자결재·공포·내부 시스템 변경 없음.

## 사용 흐름

단순 질문은 필요한 도구를 바로 사용합니다. 복합 질문은 `local_workflow_plan`으로 지역·연도·시행일과 필요한 분야를 정리하고 실제 자료를 조회합니다. `local_evidence_review`는 제공된 근거의 누락을 점검하는 보조 도구로, 원문 사실 검증을 대신하지 않습니다.

| 분야 | 하는 일 | 핵심 도구 |
|---|---|---|
| 의회 | 회의록, 발언 문맥, 부서·기간·유사 사례, 회기 준비 | `council_evidence_bundle`, `council_read_source`, `council_session_ready_pack` |
| 예산 | 공식 API 조회, 정밀 산출·증감·재원분담·다년도 비용 검산 | `budget_api_catalog`, `budget_fetch_api`, `budget_calculate` |
| 조례 | 공식 조문·버전 확인, 비교, 사업 검토, 일부개정문·신구대비 | `ordinance_search`, `ordinance_get_document`, `ordinance_review_project`, `ordinance_draft_amendment` |

예시: “○○시의 경로당 지원사업을 2027년 본예산에 반영하려고 합니다. 과거 의원 질의, 예산 산출 조건, 현행 조례상 근거를 각각 확인하고 미확인 사항을 구분해 주세요.”

의회 발언은 법적 근거 자체가 아닙니다. 다른 지역의 조례를 우리 지역 근거로 적용하지 않으며, 예산액·집행액·계약액과 원·천원·백만원을 구분합니다. 조회 실패는 자료 없음·0원으로 표시하지 않습니다. 출처와 확인 범위를 함께 제시합니다.

## 연결과 운영

직원은 기존 주소를 계속 사용합니다. 새 도구가 보이지 않으면 연결한 앱의 도구를 새로고침하거나 같은 주소로 다시 연결합니다. 표시 이름은 **지방의회·예산·조례 MCP**로 지정하면 됩니다. ChatGPT 계정별 앱 이용 가능 여부와 사용량 제한은 서버와 별개입니다. MCP는 무료 계정의 제한을 해제하거나 답변 정확성을 보장하지 않습니다.

한 Python 프로세스에서 세 패키지를 직접 실행합니다. 다른 무료 Render 서버를 중계하지 않습니다. 서버에서 Gemini 등 별도 생성형 AI를 호출하지 않으며, 호스트 AI가 실제 조회 근거와 계산 결과로 답변합니다. 큰 결과는 나누어 조회하고, 오류·시간초과·일부 결과를 구분합니다. 서구의회 홈페이지 직접 검색은 비활성입니다.

`render.yaml`은 사용자가 선택한 `0.5c-512mb` 인스턴스를 유지합니다. 기존 API 값을 Render 내부 `fromService`로 복사합니다. `LAW_OC`는 `jachi-mcp`, `LOFIN_API_KEY`·`DATA_GO_KR_SERVICE_KEY`·`KOSIS_API_KEY`는 `local-budget-mcp`에서 가져옵니다. CLIK와 기존 의회 환경변수는 유지합니다. 참조 서비스는 Blueprint 동기화에 필요하지만 실제 자료 조회 경로에는 없습니다. 참조 서비스를 삭제하기 전 환경변수를 독립 값 또는 공통 환경그룹으로 이전해야 합니다.

## API와 검증 범위

CLIK, 국가법령정보 공동활용, 지방재정365와 예산 API 카탈로그를 사용합니다. 카탈로그에는 조달·KOSIS 등 18개 항목이 있으며 항목별 명세·실조회 확인 상태가 다릅니다. 키가 설정돼 있다는 사실과 API 인증·데이터 반환 성공은 구분합니다. e호조+·보탬e 직접 연결은 없습니다.

조례의 검색 후보, 사용자가 제공한 초안, API로 조회한 원문을 구분합니다. 제정·개정안은 담당자 검토용이며 적법성 승인 결과가 아닙니다. PDF/HWP 자동 파싱이나 기관 내부자료 저장 도구는 공개하지 않습니다.

## 개발·검증

Python 3.12 권장. 실행 의존성은 `requirements.txt`에 고정합니다.

```sh
python -m pip install -r requirements.txt pytest==8.4.2
python scripts/check_config.py --manifest
python -m pytest -q
python tests/protocol_smoke.py
python scripts/verify_unified.py https://uijeong-mcp.onrender.com/mcp
```

공개 HTTP 실행에는 `UIJEONG_AUTH_MODE=public`, `UIJEONG_PUBLIC_READONLY=true`, 정확한 `UIJEONG_ALLOWED_HOSTS`가 필요합니다. `python uijeong_mcp.py --http`로 실행합니다. 운영 인증값을 Git·로그·응답에 넣지 않습니다.

설계·네 에이전트 교차검토: [통합 검토 기록](docs/INTEGRATED_RELEASE.md). 도구 흐름: [업무흐름 설명](docs/INTEGRATED_WORKFLOW.md).
