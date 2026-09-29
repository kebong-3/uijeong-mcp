"""Four executable deterministic roles. No external LLM or council-MCP call."""
from . import analytics
from .basis import checklist

class IntakeAgent:
    def run(self,ds):
        return {'role':'자료·범위','year':ds['meta']['year'],'authority':ds['meta']['authority'],
                'stage':ds['meta']['stage'],'basis':ds['meta']['basis'],'unit':ds['meta']['unit'],
                'coverage':ds['meta']['coverage'],'source_sha256':ds['file_sha256']}
class CalculationAgent:
    def run(self,ds):
        validation=analytics.validate(ds)
        calc=analytics.execution(ds) if ds['meta']['kind']=='세출' else analytics.revenue(ds)
        return validation,calc
class BasisAgent:
    def run(self,ds,topic):
        return checklist(topic,ds['meta']['year'])
class ReviewAgent:
    def run(self,ds,intake,validation,calc,basis):
        return {'analysis':'지방예산 업무 검토 묶음','dataset_ids':[ds['dataset_id']], 'unit':'원',
            'summary':{'intake_agent':intake,'calculation_agent':validation['summary'],
                       'basis_agent':basis,'review_agent':{'conclusion':'실무 확인용','auto_cut_recommendation':False,
                         'confirmed_legal_eligibility':False,'department_questions':[
                          '변경된 사업량·단가·대상자·기간에 대한 실제 증빙을 확인하세요.',
                          '이월·미지급 계약·국시비 변경내시와 회계간 전출입을 확인하세요.',
                          '자료를 연계한 AI 서비스에 내부정보 전송이 허용되는지 확인하세요.']}},
            'warnings':validation['warnings']+calc['warnings'],
            'items':[{'type':'validation',**x} for x in validation['items']]+[{'type':'calculation',**x} for x in calc['items']],
            'roles_are':'규칙 기반 실행 모듈 4개; 독립 AI 전문가 4인 검수 아님'}

def review(ds,topic='일반'):
    intake=IntakeAgent().run(ds)
    validation,calc=CalculationAgent().run(ds)
    basis=BasisAgent().run(ds,topic)
    return ReviewAgent().run(ds,intake,validation,calc,basis)

