# 실무 호출 예시

아래 JSON은 MCP 호출 인자 예시입니다. 공식 조사 결과나 실제 조직개편 이력이 아닙니다.

## 천원국시 질의·답변: 정확한 최근 2년 범위

도구 `council_evidence_bundle`:
```json
{"keyword":"천원국시","council":"광주 서구","mode":"질의답변","date_from":"2024-09-21","date_to":"2026-09-21","source":"auto","max_docs":6,"limit":10}
```
이 호출 한 번이 2년간 모든 회의록 전수조사는 아닙니다. 응답의 coverage와 next_item_offset을 확인합니다.
같은 묶음의 다음 근거는 `council_get_evidence(snapshot_id=반환값, item_offset=다음위치)`로 읽습니다.
새 목록을 수집할 때는 원래 검색조건과 함께 source_offset 또는 site_start_page를 바꿉니다.

## 반복 주제어 후보: rolling 2년

도구 `council_recurring_issues`:
```json
{"keyword":"천원국시","council":"광주 서구","period_mode":"rolling_years","years":2,"as_of":"2026-09-21","min_years":2,"source":"auto"}
```
2024-09-21~2026-09-21의 범위를 2024·2025·2026 회의연도로 나눠 조회합니다.
‘매장 확대’와 ‘매장 확대 보류’가 둘 다 있으면 같은 주제어가 반복되었다는 뜻일 뿐 요구가 같다는 뜻은 아닙니다.
반대 문면 단서는 자동 확정이 아닌 사람이 확인할 표시입니다. 일부 조회는 결과가 0건이어도 PARTIAL입니다.

## 부서 이력: 합성 예시

도구 `council_department_brief`:
```json
{"department":"새정책과","council":"광주 서구","date_from":"2024-09-21","date_to":"2026-09-21","department_aliases":[{"name":"이전정책과","valid_from":"2024-01-01","valid_to":"2024-12-31","basis":"합성 예시: 실제 사용할 때 조직개편 문서와 적용일 확인"}],"source":"auto"}
```
‘새정책과/이전정책과’와 날짜는 테스트 설명용 가상값입니다. 실제 부서 승계관계와 날짜를 확인해서 입력해야 합니다.
과거 부서명이 나타나도 회의일을 확인할 수 없으면 alias_date_unresolved로 분리합니다.

## 답변서 작성 및 후속조치

`council_format_worksheet`에 snapshot_id와 실제 event_ids를 전달합니다.
서식은 5분자유발언_회의자료, 구정질문_답변서, 행정사무감사_답변카드, 1페이지_검토보고 중 선택합니다.
근거 없는 현재 실적·사업 수치·검토의견은 자동으로 채우지 않습니다.
부서 이력으로 검색한 자료는 동일한 department_aliases를 서식 작성에도 전달합니다.
후속조치는 ‘완료보고가 있음’과 ‘실제 완료를 확인함’을 구분하고 담당자 증빙 칸을 남깁니다.
