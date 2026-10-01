import json
from datetime import date
import pytest
from pydantic import ValidationError
from jachi.procedure import ProcedureInput, screen_procedure
from jachi.models import Document, Article, ReviewInput
from integrated_workflow import local_workflow_plan
import integrated_ordinance as tools

AS_OF = date(2026, 10, 1)

def request(**kwargs):
    return ProcedureInput(jurisdiction='광주 북구', basis_title='시험 지원 조례', basis_article='제2조', **kwargs)

def codes(p, documents=()):
    return set(screen_procedure(p, AS_OF, documents)['hold_codes'])

def test_news_pattern_is_input_scenario_not_verified_incident():
    p = request(action='remediate', basis_kind='ordinance_amendment', ordinance_stage='submitted',
        dates={'ordinance_submission':'2026-09-04', 'rule_promulgation':'2026-09-15', 'rule_effective':'2026-09-15'})
    r = screen_procedure(p, AS_OF)
    assert {'NO_PLENARY_ADOPTION','MISSING_ORDINANCE_VOTE','MISSING_ORDINANCE_PROMULGATION','INCIDENT_REVIEW'} <= set(r['hold_codes'])
    assert r['status']=='HOLD_RECOMMENDED'
    assert r['input_provenance']=='USER_PROVIDED_NOT_VERIFIED'
    assert r['legal_approval'] is False
    assert '자동' in r['limits']

@pytest.mark.parametrize('stage', ['draft','submitted','committee_passed','unknown'])
def test_committee_or_internal_approval_not_final_adoption(stage):
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage=stage)
    assert 'NO_PLENARY_ADOPTION' in codes(p)

@pytest.mark.parametrize('stage', ['rejected','withdrawn','reconsideration'])
def test_unsatisfied_dependency_after_vote(stage):
    assert 'DEPENDENCY_UNRESOLVED' in codes(request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage=stage))

def test_planned_vote_is_not_completed_even_with_user_stage():
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='council_passed',
        dates={'ordinance_vote':'2026-10-05','ordinance_promulgation':'2026-10-10','basis_effective':'2026-10-10',
               'rule_promulgation':'2026-10-11'})
    assert 'VOTE_STILL_PLANNED' in codes(p)
    assert 'BASIS_NOT_YET_PROMULGATED' in codes(p)

def test_rule_before_vote_and_promulgation():
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='promulgated',
        dates={'ordinance_vote':'2026-09-18','ordinance_promulgation':'2026-09-20','basis_effective':'2026-09-20',
               'rule_promulgation':'2026-09-15'})
    assert {'RULE_BEFORE_ORDINANCE_VOTE','RULE_BEFORE_ORDINANCE_PROMULGATION'} <= codes(p)

def test_publication_after_basis_publication_and_future_commencement_is_distinct():
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='promulgated', final_text_matches='yes',
        dates={'ordinance_vote':'2026-09-20','ordinance_promulgation':'2026-09-25','basis_effective':'2026-11-01',
               'rule_promulgation':'2026-10-01','rule_effective':'2026-11-01'})
    r=screen_procedure(p, AS_OF)
    assert not r['hold_codes']  # no blanket rule that promulgation must wait until commencement
    assert r['publication_ready'] is False and r['status']=='EVIDENCE_REVIEW_REQUIRED'

def test_rule_effective_before_dependency():
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='promulgated',
        dates={'ordinance_vote':'2026-09-20','ordinance_promulgation':'2026-09-25','basis_effective':'2026-11-01',
               'rule_promulgation':'2026-10-01','rule_effective':'2026-10-01'})
    assert 'BEFORE_BASIS_EFFECTIVE_RULE_EFFECTIVE' in codes(p)

@pytest.mark.parametrize('basis',['law','current_ordinance'])
def test_independent_rule_has_no_universal_council_vote_requirement(basis):
    p=request(action='implement',basis_kind=basis,final_text_matches='yes',
        dates={'basis_effective':'2026-01-01','rule_promulgation':'2026-09-01','rule_effective':'2026-09-22','implementation':'2026-09-23'})
    r=screen_procedure(p, AS_OF)
    assert not r['hold_codes']
    assert r['legal_approval'] is False and r['implementation_ready'] is False
    assert 'OFFICIAL_BASIS_NOT_RETRIEVED' in {f['code'] for f in r['findings']}

def test_preparation_allowed_but_dependency_not_erased():
    p=request(action='prepare',basis_kind='ordinance_amendment',ordinance_stage='draft')
    r=screen_procedure(p,AS_OF)
    assert not r['hold_codes'] and '병행' in r['parallel_preparation']
    assert any(f['code']=='NO_PLENARY_ADOPTION' for f in r['findings'])

@pytest.mark.parametrize('later,earlier', [('ordinance_vote','ordinance_submission'),('ordinance_transmission','ordinance_vote'),
    ('ordinance_promulgation','ordinance_vote'),('basis_effective','ordinance_promulgation'),
    ('rule_effective','rule_promulgation'),('notice_end','notice_start')])
def test_invalid_date_order_is_visible(later,earlier):
    p=request(dates={earlier:'2026-09-20',later:'2026-09-10'})
    assert 'DATE_ORDER_'+later.upper() in codes(p)

def test_actual_implementation_before_rule():
    p=request(action='implement',basis_kind='law',dates={'implementation':'2026-09-15','rule_effective':'2026-09-20'})
    assert 'IMPLEMENTATION_BEFORE_RULE' in codes(p)

def test_exception_not_auto_bypass_and_pending_procedure_blocks():
    p=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='submitted',
        steps={'law_review':'pending','notice':'not_applicable'},exception_reason='급해서 먼저 공포')
    r=screen_procedure(p,AS_OF)
    assert {'NO_PLENARY_ADOPTION','PENDING_LAW_REVIEW'} <= set(r['hold_codes'])
    assert {'EXEMPTION_NOTICE','EXCEPTION_UNVERIFIED'} <= {f['code'] for f in r['findings']}

def test_preparing_publication_or_forms_not_automatically_prerequisite_for_itself():
    p=request(action='promulgate',basis_kind='law',final_text_matches='yes',steps={'gazette':'pending','system_forms':'pending'})
    assert 'PENDING_GAZETTE' not in codes(p) and 'PENDING_SYSTEM_FORMS' not in codes(p)
    q=p.model_copy(update={'action':'implement'})
    assert {'PENDING_GAZETTE','PENDING_SYSTEM_FORMS'} <= codes(q)

def test_short_notice_not_automatic_illegality():
    p=request(dates={'notice_start':'2026-09-01','notice_end':'2026-09-10'})
    f=next(f for f in screen_procedure(p,AS_OF)['findings'] if f['code']=='SHORT_NOTICE_REVIEW')
    assert f['severity']=='pending' and '자동 위법' in f['message']

def test_user_official_url_cannot_mark_verified():
    p=request(basis_document_id='123',source_urls=['https://www.law.go.kr/ordinInfoP.do?ordinSeq=123'])
    r=screen_procedure(p,AS_OF)
    assert not r['retrieved_basis_documents']
    with pytest.raises(ValidationError):
        ProcedureInput(**p.model_dump(),verified=True)

def test_bad_dates_unknown_keys_and_large_url_rejected():
    for args in [{'dates':{'rule_promulgation':'2026-02-30'}},{'dates':{'made_up':'2026-10-01'}},
                 {'steps':{'wrong':'done'}},{'source_urls':['a'*2001]}]:
        with pytest.raises(ValidationError): request(**args)

def test_official_mismatch_article_and_future_not_hidden():
    doc=Document(kind='ordinance',document_id='123',title='다른 조례',jurisdiction='부산 북구',
        effective_date='20261101',source_state='live',articles=[Article(key='1',label='제1조',text='시험')])
    p=request(action='implement',basis_kind='current_ordinance',basis_document_id='123')
    assert {'OFFICIAL_BASIS_IDENTITY_MISMATCH','BASIS_ARTICLE_NOT_FOUND','OFFICIAL_BASIS_FUTURE'} <= codes(p,[doc])

def test_user_document_cannot_be_official_basis():
    doc=Document(kind='ordinance',document_id='123',title='시험 지원 조례',source_state='user_provided')
    assert not screen_procedure(request(basis_document_id='123'),AS_OF,[doc])['retrieved_basis_documents']

def test_rule_questions_route_to_legislation():
    plan=local_workflow_plan('시행규칙 공포 일정 검토',jurisdiction='광주 북구',as_of='2026-10-01')
    assert plan['domains']==['ordinance']
    assert 'procedure' in plan['steps'][0]['next']

class Registry:
    def __init__(self): self.tools={}
    def tool(self,**metadata):
        def decorator(fn): self.tools[metadata['name']]=fn; return fn
        return decorator

@pytest.mark.anyio
async def test_existing_guide_backward_compatible_and_bounded():
    registry=Registry();tools.register(registry)
    result=await registry.tools['ordinance_guide']()
    assert result['external_llm_enabled'] is False and result['procedure_screening'] is None
    assert result['source_links'] and 'procedure' in result['review_schema']['properties']
    assert len(json.dumps(result,ensure_ascii=False))<30000
    assert (await registry.tools['ordinance_guide'](as_of='2026-99-01'))['status']=='INVALID_INPUT'

@pytest.mark.anyio
async def test_project_review_uses_procedure_and_quality_gate():
    registry=Registry();tools.register(registry)
    params=ReviewInput(project='규칙 공포 절차 점검',jurisdiction='광주 북구',auto_search=False,
        procedure=request(action='promulgate',basis_kind='ordinance_amendment',ordinance_stage='submitted'))
    result=await registry.tools['ordinance_review_project'](params)
    assert 'NO_PLENARY_ADOPTION' in result['feasibility']['procedure_screening']['hold_codes']
    assert 'NO_PLENARY_ADOPTION' in result['quality_gate']['procedure_hold_codes']
    assert result['usage']['llm_calls']==0

@pytest.mark.anyio
async def test_mismatched_procedure_region_refused():
    registry=Registry();tools.register(registry)
    params=ReviewInput(project='규칙 공포 검토',jurisdiction='광주 서구',auto_search=False,procedure=request())
    result=await registry.tools['ordinance_review_project'](params)
    assert result['status']=='unavailable'

@pytest.fixture
def anyio_backend(): return 'asyncio'
