import asyncio
from types import SimpleNamespace
import v3_reliability as V
import council_extensions as C
import finance_context as F
import legal_context as L
import integrated_ordinance as IO
import evidence_core as E
import openai_compat as O

def test_integration_requeries_located_titles_without_certifying(monkeypatch):
    calls=[]
    async def empty(*a,**k):return {'status':'EMPTY','items':[],'ordinances':[]}
    for name in ('_bill_context','_member_discovery','_policy_context'):
        monkeypatch.setattr(C,name,empty)
    monkeypatch.setattr(L,'context',empty)
    async def finance(topic,council,year,limit,search_terms=None):
        calls.append(('budget',search_terms))
        return {'status':'COMPLETE' if search_terms else 'EMPTY','items':[{'project_name':'문화예술 진흥 지원사업','same_project_verified':False}] if search_terms else []}
    monkeypatch.setattr(F,'context',finance)
    async def legal(query,jurisdiction):
        calls.append(('ordinance',query));return {'status':'PARTIAL','items':[{'title':query,'applicability_verified':False}]}
    monkeypatch.setattr(IO,'mention_context',legal)
    async def evidence(**kwargs):
        if kwargs['mode']=='질의답변':return {'status':'COMPLETE','items':[], 'total_items':0}
        return {'status':'COMPLETE','items':[{'source_kind':'OFFICIAL_FETCHED','event_id':'evt_1','speech':{
            'text':'문화예술 진흥 및 지원 조례에 따라 문화예술 진흥 지원사업을 운영합니다.',
            'citation':{'source_kind':'OFFICIAL_FETCHED','docid':'D1','turn_index':3}}}]}
    backend=SimpleNamespace(pick_council=lambda q:('X','서울특별시 종로구의회',None),council_evidence_bundle=evidence)
    r=asyncio.run(V.context_pack(backend,'문화예술',fiscal_year=2026))
    assert ('ordinance','문화예술 진흥 및 지원 조례') in calls
    assert any(kind=='budget' and terms for kind,terms in calls)
    assert r['search_strategy']['expanded']
    assert r['linked_review']['budget']['discovered_candidates'] == 1
    assert len(r['linked_review']['candidate_index']['budget']) == 1
    assert len(r['linked_review']['candidate_index']['ordinance']) == 1
    assert r['ready_for_submission'] is False
    assert r['linked_review']['same_project_verified'] is False
    assert r['linked_review']['legal_approval'] is False

def test_search_short_council_uses_same_evidence_and_fetch_with_missing_url():
    O._SEARCH_CACHE.clear();calls=[]
    class Backend:
        async def council_evidence_bundle(self,**kwargs):
            calls.append(kwargs)
            return {'status':'PARTIAL','items':[{'docid':'D42','kind':'발언','speech':{'turn_index':8},'provenance':{'source':'CLIK'}}]}
        async def council_read_source(self,**kwargs):
            assert kwargs['ref']=='D42'
            return {'status':'PARTIAL','turns':[{'idx':8,'text':'실제 반환된 조회 원문'}],'next_start_turn':9}
    tools=O.build_tools(Backend())
    async def execute():
        found=await tools['search']('부산진구의회 청년월세');return found,await tools['fetch'](found.results[0].id)
    found,fetched=asyncio.run(execute())
    assert calls[0]['council']=='부산광역시 부산진구의회'
    assert calls[0]['keyword']=='청년월세'
    assert '원문링크 미제공' in found.results[0].title
    assert fetched.metadata['direct_document_url'] is False
    assert fetched.metadata['url_kind']=='OFFICIAL_SERVICE_PORTAL'
    assert '실제 반환된 조회 원문' in fetched.text

def test_merge_multiquery_has_no_overlap_on_continuation():
    events=[{'event_id':'evt1','matched_query':'청년월세'},{'event_id':'evt2','matched_query':'청년 월세'},{'event_id':'evt1','matched_query':'청년 월세'}]
    merged=E.merge_events(events)
    assert len(merged)==2
    assert merged[0]['matched_queries']==['청년월세','청년 월세']
    assert not {e['event_id'] for e in merged[:1]} & {e['event_id'] for e in merged[1:]}


def test_formal_report_after_greeting_is_not_an_answer():
    text = '안녕하십니까? 건축과장입니다. 위원님들의 노고에 감사드립니다. 건축과 소관 사항에 대한 2026년도 주요 업무추진실적 보고를 드리겠습니다. 사업비는 2억원입니다.'
    assert E.classify_act('executive','건축과장',text) == 'report'
    assert E.classify_act('executive','건축과장','위원님 질문에 답변드리겠습니다. 다음 회기에 보고하겠습니다.') == 'answer_candidate'


def test_unambiguous_city_shortform_does_not_use_default():
    council,drop=O._best_council('수원 공동주택 회의록')
    assert council == '경기도 수원시의회'
    assert O._keyword('수원 공동주택 회의록',drop) == '공동주택'


def test_fiscal_short_jurisdiction_uses_shared_identity():
    assert V.finance_belongs({'laf_hg_nm':'경기수원시'},'수원시')
    assert V.finance_belongs({'laf_hg_nm':'경기수원시'},'경기도 수원시의회')
    assert not V.finance_belongs({'laf_hg_nm':'서울중구'},'중구')
    assert not V.finance_belongs({'laf_hg_nm':'부산중구'},'서울특별시 중구')

def test_located_target_subject_is_first_shared_search_seed(monkeypatch):
    calls=[]
    async def empty(*a,**k):return {'status':'EMPTY','items':[],'ordinances':[]}
    for name in ('_bill_context','_member_discovery','_policy_context'):
        monkeypatch.setattr(C,name,empty)
    monkeypatch.setattr(L,'context',empty)
    async def finance(topic,council,year,limit,search_terms=None):
        if search_terms:calls.append(('budget',search_terms))
        return {'status':'EMPTY','items':[]}
    monkeypatch.setattr(F,'context',finance)
    async def legal(query,jurisdiction):
        calls.append(('ordinance',query));return {'status':'EMPTY','items':[]}
    monkeypatch.setattr(IO,'mention_context',legal)
    async def evidence(**kwargs):
        return {'status':'COMPLETE','items':[{'source_kind':'OFFICIAL_FETCHED','speech':{
            'text':'홀몸 어르신을 대상으로 행복돌봄을 운영합니다.',
            'citation':{'source_kind':'OFFICIAL_FETCHED','docid':'S1','turn_index':8}}}]}
    backend=SimpleNamespace(pick_council=lambda q:('X','서울특별시 종로구의회',None),council_evidence_bundle=evidence)
    r=asyncio.run(V.context_pack(backend,'행복돌봄',fiscal_year=2026))
    assert ('ordinance','홀몸 어르신') in calls
    assert next(v for kind,v in calls if kind=='budget')[0]=='홀몸 어르신'
    assert r['discovery_candidates']['target_subjects'][0]['same_project_verified'] is False
    assert r['linked_review']['legal_approval'] is False
