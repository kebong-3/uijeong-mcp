# 2.5.0-rc.1

- Add one-call response preparation, exact citation audit, dimension-aware metric comparison, and side-by-side evidence review.
- Add a Korean MCP prompt, two resources, supporting official document routes, and synthetic runnable examples.
- Fix legacy answer review counting unresolved support as a linked claim.
- Keep new audit outputs fail-closed when response budget truncates inspection results.
- Retry transient robots lookup failures instead of caching them as six-hour policy denial; retain actual robots exclusions.
- Offload CLIK source detail parsing from the event loop.
- Preserve auth, public snapshot schema, and existing tool signatures. Work/lite/full add four tools; core is unchanged.

# 변경 이력

## 2.4.0-rc.1 — 2026-09-21

사용자 제공 2.3.1 기반. 원격 배포/로그인 완료를 의미하지 않는 후보판.

### 동작 수정
- 최종 부서 분류에도 별칭·적용기간 반영. 미상 날짜는 자동 포함 대신 재검토 목록으로 반환.
- PARTIAL/ERROR 전파 보존. 연도별 실패, 미조회 페이지, 스냅샷 불가를 0건과 구분.
- rolling_years 및 날짜 명시 기능. 달력연도 기본값은 호환을 위해 유지.
- 반복 단어에 요청 문면 단서 첨부. 동일 요구·반대 요구의 의미 관계를 자동 확정하지 않음.
- 원문 답변 메타데이터 유지, 회의가 다른 동일 약속 보존, 선택 질의에 속한 후속조치만 서식에 반영.
- 모든 event_id를 확인하여 일부 잘못된 ID가 섞여도 오류 반환.
- 한글 보관 용량을 UTF-8 바이트로 계산. 사용자별 근거 조회 분리와 전체 저장 상한 동시 적용.

### 인증·운영
- 기본 정적 Bearer와 선택 OAuth introspection을 분리. 인증서버 기능은 포함하지 않음.
- iss/aud/exp/nbf/scope/sub 확인, 기본 무캐시, 인증서버 장애 시 닫힘(503), 토큰 리디렉션 금지.
- 보호 리소스 메타데이터·401/403 안내, 최소 정보 healthz 제공.
- 단일 버전 상수, 코드 지문, manifest 대조, 설정 검사와 배포 검사 스크립트.
- service 계층에서 SDK wire 변환을 분리해 실제 업무 로직의 독립 시험 가능.

### 호환 및 주의
- 기존 core/work/lite/full 도구 개수 및 주요 도구 이름 유지.
- extra_terms는 적용기간 없는 부서 별칭의 호환 인자. 새 department_aliases는 basis 필수, 최대2개.
- 부서 별칭·추가 검색어 초과나 잘못된 입력을 조용히 잘라내지 않고 거부.
- recurring_issues에 department와 keyword를 동시에 입력하면 INVALID_INPUT.
- 업데이트 전 공유 HTTP 스냅샷은 새 요청별 범위에 맞지 않아 재조회가 필요할 수 있음. 권한 경계를 우회하여 재사용하지 않음.
- OAuth 모드에서는 기존 UIJEONG_BEARER_TOKEN을 제거해야 함. 기존 Render 환경변수가 파일 교체만으로 삭제된다고 가정하지 말 것.
- 자료 동기화 작업·새 지자체 크롤러·외부 인증서버 구축은 이번 범위가 아님.
