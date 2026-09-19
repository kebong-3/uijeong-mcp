# 의정소통 MCP 2.3.0

공개 지방의회 회의록에서 제안·질의와 집행부 답변을 확인하고, 근거가 연결된 답변자료와 후속조치 확인표를 만드는 MCP 서버입니다.

**본 패키지는 소스·로컬 통신 검증본입니다. 기존 Render/GitHub 운영 서버를 변경하지 않았습니다.** 첨부 v1.1 코드와 v1.2 검증보고서를 바탕으로 2.0.0을 재구현했고, 2.1.0에서 실제 규모 회의록으로 응답 크기·보관 압력·도구 노출을 측정해 보완했습니다. v1.2 소스 ZIP은 입력으로 제공되지 않았습니다.

## 2.3.0 실무 기능 — 부서에서 시작하는 흐름

담당자가 의회 대응을 시작하는 단위는 주제어가 아니라 소관 부서입니다. "성인지예산"을 검색하려면
그 사업이 쟁점이라는 것을 이미 알아야 하는데, 새로 발령받은 담당자는 그것부터 모릅니다.
2.3.0은 **부서명만으로 시작해** 우리 과가 의회에서 무엇을 받았는지, 무엇이 해마다 반복되는지,
그것을 기관 서식 칸에 어떻게 배치할지까지 이어지도록 도구 3개를 더했습니다.

- `council_department_brief` — 검색어 없이 부서명만으로 그 부서가 받은 질의·답변·후속조치를 모읍니다.
  부서명은 질의 본문이 아니라 답변자 직함에 나타나므로, 부서명으로 회의록을 찾은 뒤 직함의 부서 어간으로 가려냅니다.
  같은 부서 팀장의 대리답변도 함께 잡습니다. 조직개편 전 명칭은 `extra_terms`로 최대 2개 더합니다.
- `council_recurring_issues` — 여러 회의연도에 반복된 요구를 셉니다. 질의 성격 발언만 세며 답변은 세지 않습니다.
  집계 단위는 연도·회의이고 의원 개인이 아닙니다. 결과는 '반복 확인'이지 다음 회기 질문의 예측이 아닙니다.
- `council_format_worksheet` — 확인된 발언과 담당자 제공자료를 기관 회의자료 서식 칸에 배치하고
  붙여넣을 본문을 만듭니다. 5분자유발언 회의자료·구정질문 답변서·행정사무감사 답변카드·1페이지 검토보고 네 가지.
  검토의견·답변요지처럼 판단이 필요한 칸은 **비운 채 담당자 확인 대상으로 남기며 문장을 만들어 넣지 않습니다.**

세 도구 모두 의원 개인 단위 집계·성향 분석을 하지 않고, 비공개 입력을 서버에 저장하지 않습니다.
답변 미연결은 '이번 확인 범위의 결과'이며 답변하지 않았다는 판정이 아닙니다.

## 2.2.0 실무 기능

제공된 클로드 개선본 v2.1.0을 기반으로 회기 준비 → 실제 근거 → 답변카드 → 초안·수치 점검 → 후속 증빙 확인을 구현했습니다. 상세 기획·입력 예시·설치 순서는 [실무 안내서](docs/practical-guide-v22.md)에 있습니다.

- 7가지 회의 유형의 준비표와 쟁점별 답변카드.
- 초안의 수치·단위·제공근거 연결 및 표현 점검. 의미의 진실성을 자동 승인하지 않음.
- 증감액·증감률·집행잔액·집행률 산술검사.
- 완료보고와 증빙 구비를 분리한 후속조치 확인표. 신규 입력은 서버에 저장하지 않음.
- 응답 축약 후 목록·발언 이어보기 위치 보정, 표시 인용의 범위·해시 구분, 초대형 오류 메시지 제한.
- 실무 권장 프로필 `work`(14개). 전체 도구 명세는 `docs/tool-schemas.json`에 포함.

## 이전 버전 2.1.0에서 보완한 것

아래 수치는 제공된 2.1.0의 기록입니다. 이번 버전 비교 재현은 `docs/verification/v21-v22-comparison.json`을 확인하세요.

2.0.0 패키지를 실제 규모(발언 879개) 합성 회의록으로 호출해 측정한 결과를 반영했습니다. 측정 근거와 재현 방법은 `docs/verification/v21-input/response-budget.md`에 있습니다.

| 관측한 문제 | 조치 |
|---|---|
| `council_prepare_pack`이 3,271,918자 반환 — 클라이언트 입력 한도 초과 위험 | 응답 예산 계층 신설. 같은 조건에서 전송 24,553자 |
| `briefing`과 `followup_ledger`·`question_candidates`가 같은 본문을 중복 제공 | 절마다 한 번만 제공하고 `*_ref`로 위치만 표시 |
| `discussion_evidence`가 발언 수만큼(882건) 증가, 상한 인자 없음 | `max_evidence`(기본 12) 추가, 생략 건수를 `evidence_totals`에 표시 |
| 텍스트 블록과 `structuredContent`에 동일 JSON을 실어 전송량 2배 | 소형 결과는 규격 권고대로 JSON 유지, 대형 결과는 요약 + 구조화 결과 |
| 스냅샷 500건 도달 시 모든 이용자의 이어보기 정지 | 한도 2,000건·256MB로 조정하고 가장 오래된 묶음부터 비우며 `warnings`에 고지 |
| 도구 25개 노출 — v1.2 보고서의 다섯 진입도구 권고와 상충 | `UIJEONG_PROFILE=core`(5개) 추가, 배포 기본값을 core로 제안 |

응답 축약은 근거를 버리는 것이 아닙니다. 줄인 목록·인용은 건수와 회수 경로를 함께 남기고, 축약이 일어나면 `COMPLETE`를 `PARTIAL`로 내립니다.

## 바로 사용

Python 3.11 또는 3.12 권장. 검증 환경은 Python 3.12 / MCP SDK 1.30.0입니다.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows에서는 `.venv\Scripts\activate`로 가상환경을 활성화합니다.

이미 운영 서버에 설정한 **CLIK_API_KEY를 그대로 유지**합니다. 코드는 운영 키를 추출하거나 ZIP에 넣지 않습니다. 로컬에서는 운영체제 환경변수 또는 클라이언트의 비밀 설정에 키를 입력합니다. `.env.example`은 설정 참고용이며 `.env`를 자동으로 읽지는 않습니다.

```bash
python uijeong_mcp.py          # 로컬 stdio MCP
python uijeong_mcp.py --check  # 실제 CLIK·서구 홈페이지 진단, API 호출 발생
```

MCP 클라이언트 stdio 설정 예시:

```json
{
  "mcpServers": {
    "uijeong": {
      "command": "/absolute/path/.venv/bin/python",
      "args": ["/absolute/path/uijeong-mcp/uijeong_mcp.py"],
      "env": {"CLIK_API_KEY": "발급받은 키를 비밀 설정에 입력", "UIJEONG_PROFILE": "work"}
    }
  }
}
```

위 경로는 설치 위치의 절대경로로 바꿉니다. 실제 키가 포함된 클라이언트 설정은 Git에 올리지 않습니다.

## 권장 업무 흐름

### 부서 담당자 (2.3.0 권장)

1. `council_department_brief(department="노인복지과", council="광주 서구")` → 우리 과가 받은 질의·답변·후속조치.
2. `council_recurring_issues(department="노인복지과", years=3)` → 해마다 반복된 요구 확인.
3. `council_get_evidence(snapshot_id=..., collection="items")` → 원문 근거 이어보기, `council_read_source`로 원문 확인.
4. `council_format_worksheet(form="행정사무감사_답변카드", topic="노인복지관 급식", department="노인복지과", snapshot_id=..., event_ids=[...], facts=[...])` → 기관 서식 배치.
5. `council_review_answer(draft=..., facts=[...])`·`council_check_figures(data=[...])` → 제출 전 수치·표현 점검.

사업명을 이미 아는 경우에는 3번의 `council_evidence_bundle` 검색부터 시작해도 됩니다.

### 주제어 기준 (기존)

1. `council_status()` → 버전, 도구 명세와 코드 해시 확인. `live=True`일 때만 실제 외부 연결 점검.
2. `council_find_council("광주 서구")` → 공식 코드 확인. 단순 `서구`는 지역을 확정하지 않음.
3. `council_evidence_bundle(keyword="성인지예산", council="광주 서구", date_from="2023-01-01", date_to="2025-12-31")` → 근거 목록.
4. `council_read_source(ref="검색결과 docid", start_turn=0, start_char=0)` → 원문 확인. 서구 홈페이지 key는 `site:문서키`.
5. `council_prepare_pack(keyword="성인지예산", council="광주 서구", date_from="2023-01-01", date_to="2025-12-31")` → 브리핑·준비 질문·후속조치 확인표.
6. `council_period_review(keyword="성인지예산", years=3, include_current_year=False)` → 완료된 3개 회의연도를 각각 검색.

`council_data_sources`에는 공식 사이트·현재 코드·조사일·접속 관측·지원 어댑터가 들어 있습니다. 사이트 목록에 있다고 자동수집이 가능한 것은 아닙니다. `council_discover_minutes_links`는 담당자가 제공한 공식 HTML에서 진입 링크를 찾는 보조 도구로 네트워크 요청을 하지 않습니다.

## 신규 핵심 기능

| 도구 | 실제 제공 내용 |
|---|---|
| council_evidence_bundle | 네 검색모드, 출처별 범위·오류, 원문 발언·문자 위치·해시, 공개 근거 스냅샷 |
| council_period_review | 연도마다 같은 한도로 조회, 올해 포함 여부와 회의연도 명시 |
| council_read_source | 긴 발언 문자 단위 이어읽기, 원본 첨부와 열람한 본문 구분 |
| council_prepare_pack | 근거 있는 답변준비 초안, 질문 후보, 후속조치 확인표 |
| council_data_sources | 공식 코드·사이트·회의록 주소와 연동 상태 조회 |
| council_discover_minutes_links | 제공한 공식 HTML 안의 회의록 링크 탐색 |
| council_status | 버전·커밋·코드/도구 스키마 해시·KST 호출 추정량·선택적 실연결 검사 |
| council_department_brief | 검색어 없이 부서명만으로 소관 질의·답변·후속조치 정리(직함 기준 분류) |
| council_recurring_issues | 회의연도별 반복 요구 집계. 연도·회의 단위이며 의원 개인 단위 아님 |
| council_format_worksheet | 확인된 근거를 기관 회의자료 서식 칸에 배치, 판단 칸은 빈칸 유지 |

기존 도구 이름은 유지합니다. 통합 검색과 원문 열기 호환 도구는 새 근거 엔진을 사용하며 일부 출력 형식이 바뀌었습니다. 기존 수집 보조도구보다 새 구조화 도구를 우선 사용하세요.

### 도구 프로필

| `UIJEONG_PROFILE` | 도구 수 | 쓰는 곳 |
|---|---|---|
| `core` | 5 | 대외 공개·ChatGPT 커넥터. 조사범위 확인 → 근거검색 → 원문 열기 → 준비자료 → 상태점검 |
| `work` | 14 | 신규 실무 흐름 권장. 부서 진입 3종 포함 |
| `lite` | 22 | 기관 내부에서 기존 보조도구까지 함께 쓰는 경우 |
| `full` | 34 | 개발·검증. 호환용 구버전 도구 전부 포함 |

좁은 프로필의 도구는 넓은 프로필에도 모두 있습니다. 실무 흐름에는 `work`를 권장하며 검색 중심으로만 쓸 때는 `core`를 선택합니다. 알 수 없는 값을 넣으면 `full`로 동작합니다.

### 응답 크기

도구 결과는 모델의 컨텍스트 안에서 소비되므로 한도를 넘는 결과는 더 완전한 것이 아니라 쓰지 못하는 결과입니다. 구조화 결과는 기본 30,000자 안으로 맞추며, `UIJEONG_MAX_RESPONSE_CHARS`로 8,000~200,000 범위에서 조정합니다.

- 축약된 목록에는 `<이름>_omitted`에 생략 건수·전체 건수·회수 경로가 붙습니다.
- 잘린 인용에는 `<이름>_truncated`에 남긴 글자수·원문 글자수가 붙고, 문구는 고치지 않고 앞에서만 자릅니다.
- `record_id`·`turn_index`·`char_start`·`char_end`·`quote_sha256`·`snapshot_id` 같은 식별자와 이어보기 위치는 축약 대상이 아닙니다.
- 전체 축약 내역은 `response_budget.reduced`에 남습니다.
- 8,000자 이하 결과는 MCP 권고대로 텍스트 블록에 직렬화 JSON을 함께 담고, 그보다 크면 요약을 담습니다(`UIJEONG_TEXT_JSON_MAX_CHARS`).

## 근거와 범위 읽기

- COMPLETE: 이번 요청 범위 확인 완료. 기관 전체 데이터의 완전성을 뜻하지 않음.
- PARTIAL: 한도·실패·미열람·미표시 결과 존재. coverage와 이어보기 위치 확인.
- EMPTY: 확인한 범위에서 해당 결과가 발견되지 않음.
- ERROR: 자료 조회 또는 처리 실패. 자료 부재로 해석하지 않음.
- INVALID_INPUT: 날짜·의회·조회조건 오류. 입력 정정 필요.

`ERROR`·`INVALID_INPUT`은 새 구조화 도구에서 MCP `isError=true`로 전달됩니다. 합성자료는 SYNTHETIC, 붙여넣기는 USER_PROVIDED이며 공식 자료로 승격하지 않습니다. 원문 인용은 실제 표현을 유지하고, 실무 설명은 중립적으로 씁니다.

`fiscal_year=null`은 회계연도를 따로 확인하지 않았다는 뜻입니다. 과거 발언과 현재 시행 여부도 구분합니다. ‘후속 증빙 미확인’은 ‘미이행’ 판정이 아닙니다.

같은 `snapshot_id`로 `item_offset`을 늘리면 이번에 확보한 동일 근거를 재조회 없이 이어봅니다. 원래 검색조건도 그대로 전달합니다. 다음 API 목록은 `source_offset`, 홈페이지 다음 목록은 `site_start_page`를 사용합니다. 홈페이지 미열람 key는 coverage의 `pending_refs`에서 직접 엽니다. 상류 목록은 새 회의 추가로 변할 수 있으므로 전체 원격 DB를 고정한 스냅샷은 아닙니다.

## HTTP·Render

```bash
python uijeong_mcp.py --http
```

기본은 `127.0.0.1:8000/mcp`입니다. 외부 공개에는 아래 설정이 필요합니다.

| 환경변수 | 설정 |
|---|---|
| CLIK_API_KEY | 기존 발급키 유지 |
| UIJEONG_BIND_HOST | 외부 서버는 `0.0.0.0` |
| UIJEONG_ALLOWED_HOSTS | 실제 배포 도메인 또는 도메인:포트, 쉼표 구분; 와일드카드 금지 |
| UIJEONG_BEARER_TOKEN | 32자 이상의 충분히 무작위인 비밀 토큰; 클라이언트 Authorization Bearer와 동일 |
| UIJEONG_ALLOWED_ORIGINS | 브라우저를 쓸 경우 허용할 정확한 HTTPS Origin; 불필요하면 비워둠 |
| UIJEONG_STATE_DB | 영속 볼륨의 SQLite 절대경로, 예 `/var/data/uijeong.sqlite3` |
| UIJEONG_PROFILE | `work`(실무 권장) · `core` · `lite` · `full` |
| UIJEONG_MAX_RESPONSE_CHARS | 구조화 결과 한도, 기본 30000 |
| UIJEONG_SNAPSHOT_MAX_ENTRIES | 근거 묶음 보관 건수, 기본 2000 |
| UIJEONG_SNAPSHOT_MAX_TOTAL_BYTES | 근거 묶음 총 용량, 기본 268435456 |

제공 `render.yaml`은 환경변수를 입력하고 배포하는 템플릿입니다. 자동으로 현재 서비스를 교체하지 않습니다. 무료/임시 디스크는 재배포 시 상태가 사라질 수 있으므로 영속 저장은 별도로 확보합니다. 같은 SQLite 파일을 공유하는 프로세스만 호출량을 공유하며 다른 서버에서 동일 키를 사용한 횟수는 합산되지 않습니다.

**이 서버의 정적 Bearer 인증은 OAuth가 아닙니다.** 해당 클라이언트가 Authorization 헤더 설정을 지원해야 직접 연결됩니다. OAuth만 지원하는 연결 화면에서는 별도의 OAuth 게이트웨이 연계가 필요하며, 이 패키지는 OAuth 인증기관·사용자 로그인 기능을 구현하지 않았습니다. 기존 익명 HTTP 연결에 그대로 덮어쓰면 인증 설정 전에는 401이 발생합니다. 먼저 시험 환경에서 클라이언트 인증 호환성을 확인하세요.

원격 HTTP의 로컬 보관함 검색은 기본 차단합니다. 별도 기관용 서버에서만 관리자가 `UIJEONG_ALLOW_LOCAL_ARCHIVE_HTTP=1`로 허용할 수 있으며, 동일 서버 이용자가 그 보관함 내용을 조회할 수 있습니다. 로컬 원문과 붙여넣기를 공개 근거 스냅샷에 저장하지 않습니다.

## 검증·배포 확인

```bash
python -m pip install pytest==8.4.2
python -m pytest -q
python tests/regression_r0.py
python tests/offline_check.py
python tests/protocol_smoke.py
```

실제 SDK를 쓰며 SDK 대체 모듈은 없습니다. pytest는 288건(제공 2.2.0의 247건 + 부서 진입·반복 쟁점·서식 신규 41건)이 통과했습니다. 기존 별도 회귀·오프라인 점검 41건도 통과했습니다. 프로토콜 검사는 외부 API 호출 없이 stdio와 실제 TCP HTTP 연결·인증·Origin·요청 크기·구조화 출력·오류를 검사합니다. GitHub Actions에는 Python 3.11/3.12 검사를 넣었습니다. 이 세션에서 GitHub Actions를 원격 실행한 것은 아닙니다.

배포 후 `council_status(live=True)`의 버전 2.3.0·커밋·module_sha256을 `release_manifest.json`과 대조하고 클라이언트 도구 목록을 새로 읽으세요. 단순 서버 재시작이 새 커밋 배포를 뜻하지 않습니다.

## 범위와 다음 개발 단계

현재 직접 데이터 어댑터는 CLIK와 서구의회 홈페이지입니다. 전국 디렉터리는 탐색 기반이며 전국 홈페이지 본문 자동수집 완료가 아닙니다. CLIK 회의록·의안·정책정보 API를 구현했으며 별도의 법령·지방재정 API는 docs/data-api-guide.md에 필요성·신청 경로를 정리한 연계 후보입니다.

PDF/HWP/HWPX/OCR·동적 회의록 화면, 기관별 조직개편 이력, 조치완료 증빙 자동판정, 임베딩 전국 전수색인, 다중 서버 공용 DB, OAuth는 포함하지 않습니다. 임의의 회의록을 완벽히 이해하거나 의회 질문을 예측한다고 주장하지 않습니다. 준비 질문은 확인된 발언을 바탕으로 한 실무 검토용 후보입니다.

더 큰 근거 묶음이 저장 한도를 넘으면 PARTIAL과 재조회 대상 ID를 반환합니다. 원문은 `council_read_source`로 별도 확인하세요. 스냅샷은 기본 24시간 후 만료되며 원본 PDF/HWP 파일의 법적 보존 시스템을 대체하지 않습니다.

보관 건수·용량 한도에 닿으면 가장 오래된 묶음부터 비우고 `warnings`에 `SNAPSHOT_EVICTED`로 알립니다. 비워진 `snapshot_id`로 이어보던 요청은 검색조건을 다시 지정해 조회해야 합니다. 라이브러리 기본값은 여전히 '거절'이며, 공유 배포에서만 이 교환을 명시적으로 켭니다.

응답 예산은 크기만 보장합니다. 회의록 해석 정확도·전국 재현율과는 별개이며, 축약이 잦다면 `max_docs`·`limit`·`max_evidence`를 줄이고 기간을 좁히는 편이 근거 확인에 유리합니다.

문서: docs/product-design.md · docs/data-api-guide.md · docs/verification/.
