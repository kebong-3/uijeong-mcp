# 응답 크기 관측과 보완 (2.1.0)

측정일: 2026-09-18. 대상: 이 저장소의 2.0.0 패키지. 실행: 로컬, 가짜 상류(CLIK·홈페이지)
어댑터. 본문은 규모만 실제와 맞춘 합성자료이며 실제 발언·수치가 아니다.

## 왜 측정했는가

MCP 도구 결과는 모델 컨텍스트 안에서 소비된다. 한도를 넘는 결과는 더 완전한 답이
아니라 쓰지 못하는 답이고, 클라이언트는 이를 잘라내거나 호출을 실패시킨다. 2.0.0의
기능 시험 164건은 모두 통과했지만 반환 크기를 검사하는 항목은 없었다.

v1.2 보고서 T06에서 실제 CLIK 회의록 한 건이 발언 879개 규모로 관측되었다. 그 규모로
도구를 호출해 크기를 측정했다.

## 관측값 (발언 879개 × 3건, `max_docs=3`)

| 도구 | 2.0.0 반환 | 2.1.0 MCP 경계 전송 |
|---|---|---|
| council_prepare_pack | 3,271,918자 (약 160만 토큰) | 24,553자 |
| council_evidence_bundle | 36,902자 | 29,400자 |
| council_period_review (years=3) | 75,700자 | 4,059자 |

2.0.0의 `prepare_pack` 3.2MB는 어떤 모델의 컨텍스트에도 들어가지 않는다. 원인은 셋이다.

1. `briefing.discussion_evidence`가 이벤트 수만큼 증가(882건)하고 상한 인자가 없었다.
2. `briefing.followup_candidates`와 `followup_ledger.entries`가 완전히 같은 JSON이었다.
   `briefing.preparation_questions`와 `question_candidates.candidates`도 같았다.
   `build_briefing`이 내부에서 두 함수를 다시 호출하고, `prepare_pack`이 같은 결과를
   최상위에도 넣었다.
3. `wire_result`가 같은 JSON을 텍스트 블록과 `structuredContent`에 모두 실어
   전송량이 두 배였다(중복비율 1.00 실측).

## 보완 내용

- `response_budget.py`: 구조화 결과를 한도(기본 30,000자) 안으로 축약한다. 목록 상한 →
  인용 축약 → 일반 문자열 축약 → 최소 봉투 순으로 적용하고, 보고 블록까지 포함한
  최종 객체 크기로 판정한다. 한도는 보장이며 최선노력이 아니다.
- 축약분은 `<이름>_omitted`(건수·전체·회수경로), `<이름>_truncated`(남긴·원문 글자수),
  `response_budget.reduced`에 남는다. 식별자와 이어보기 위치는 축약하지 않는다.
- 축약이 일어나면 `COMPLETE`를 `PARTIAL`로 내린다.
- `build_briefing(max_evidence, include_derived)` 추가. `prepare_pack`은 각 절을 한 번만
  제공하고 `*_ref`로 위치를 가리킨다.
- 텍스트 블록: 8,000자 이하 결과는 MCP 권고대로 직렬화 JSON을 유지하고, 그보다 크면
  상태·범위·주요 근거·한계를 담은 요약을 보낸다.

## 재현

```bash
python -m pytest tests/test_response_budget.py tests/test_final_hardening.py \
                 tests/test_realistic_size.py -q
```

`tests/test_realistic_size.py`가 발언 879개 × 3건 조건을 고정한다. 한도 초과,
절 중복, 생략 미고지가 생기면 실패한다.

## 남은 한계

- 응답 예산은 크기만 보장한다. 회의록 해석 정확도·전국 재현율과는 무관하다.
- 축약된 결과로 업무 판단을 하기에 부족하면 범위를 좁혀 다시 조회해야 한다. 한도를
  올리는 것은 클라이언트 컨텍스트를 그만큼 소비하는 선택이다.
- 토큰 환산은 문자수 절반으로 어림한 값이며 실제 토크나이저 기준이 아니다.
- 이 측정은 합성 상류로 수행했다. 실제 CLIK 응답의 필드 길이 분포는 다를 수 있다.
