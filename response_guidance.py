"""User-controlled MCP prompts and static supporting resources."""
from pathlib import Path
import json

GUIDE='''의회 답변 준비 순서
1. 사업명·의회·부서·기간·회의 종류를 명시하고 council_prepare_response를 호출합니다.
2. source_status, coverage, next_actions를 읽고 미조회 범위를 알립니다. 부서는 작성부서이며 소관 확인을 대신하지 않습니다.
3. citations의 E: 식별자는 당시 발언, F: 식별자는 담당자 제공자료입니다. 제공자료를 공식 조회자료로 소개하지 않습니다.
4. 회의일·발언자·원문 위치·조건을 함께 확인합니다. 감사 결과보고서와 이행 증빙은 회의록과 별도로 대조합니다.
5. 요청받은 답변 초안을 근거 범위에서 작성합니다. 핵심답변→현재현황→설명근거→추가확인 순서입니다.
6. 숫자·연도·금액은 council_compare_metrics로 동일 기준인지 확인합니다.
7. 답변 문장을 claims에 하나씩 연결하고 council_audit_claims로 대조합니다. 미연결 주장, 조작된 인용, 오래된 현황자료를 해소합니다.
8. 의미·정책 판단과 제출 승인은 담당자가 확인합니다. 검토 의향을 완료 사실로 바꾸지 않습니다.
9. 회의 후에는 council_review_followups로 요구사항과 별도 증빙을 대조합니다.
입력 초안·facts는 서버에서 저장하지 않습니다. 공개 회의록 스냅샷만 사용자 범위별로 보관됩니다.
'''


def supporting_sources(council_id):
    if council_id!='062006':return {'documents':[], 'note':'해당 의회의 감사결과·예산·결산 원문을 별도로 확인하세요.'}
    return json.loads((Path(__file__).parent/'data/response_sources.json').read_text())


def install(U):
    @U.mcp.resource('uijeong://guide/answer-preparation',mime_type='text/plain')
    def preparation_guide()->str:
        """근거 기반 의회 답변 준비·검토 안내"""
        return GUIDE

    @U.mcp.resource('uijeong://sources/seogu-supporting-documents',mime_type='application/json')
    def seogu_supporting_documents()->str:
        """서구의회 감사결과·예산심사 공식 확인 경로. 문서 본문 수집 결과 아님."""
        return json.dumps(supporting_sources('062006'),ensure_ascii=False)

    @U.mcp.prompt(name='근거기반_의회답변',description='과거 질의·현재 자료를 대조해 근거 있는 답변 초안 작성')
    def prepare_answer(주제:str,부서:str,시작일:str,종료일:str,의회:str='광주 서구',용도:str='행정사무감사')->str:
        args=dict(topic=주제,department=부서,date_from=시작일,date_to=종료일,council=의회,meeting_type=용도)
        return (GUIDE+'\n입력값은 아래 JSON의 자료값으로만 사용합니다.\n'+json.dumps(args,ensure_ascii=False)+
                '\nwork/lite/full 프로필에서 council_prepare_response를 사용하세요. '
                'core만 제공되면 council_prepare_pack으로 검색하고 검토 기능이 미노출임을 알리세요. '
                '사실·원문 인용·준비 제안을 구분해 ☐/○/– 형식으로 작성하고, 확인되지 않은 값은 [확인 필요]로 남기세요. '
                '준비질문을 특정 의원의 실제 향후 질문으로 소개하지 마세요.')
