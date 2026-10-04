"""Independent protection against silently losing integrated findings on the wire."""
import copy
import pytest
from response_budget import apply_budget,size_of

def payload():
    return {'status':'PARTIAL','topic':'문화예술','ready_for_submission':False,
        'linked_review':{'budget':{'status':'EMPTY','initial_candidates':0,'discovered_candidates':1,'amounts_verified':False},
            'ordinance':{'status':'EMPTY','initial_candidates':0,'discovered_candidates':1,'applicability_verified':False},
            'relationships':[{'domain':'budget','term':'문화예술 지원사업','status':'PARTIAL',
                'same_project_verified':False,'applicability_verified':False,
                'continuation':{'tool':'council_finance_context','arguments':{'topic':'문화예술 지원사업','council':'서울특별시 종로구','fiscal_year':2026,'limit':1}}}],
            'unresolved':['동일사업 여부 미확인','단위 미확인'],
            'ready_for_submission':False,'legal_approval':False,'same_project_verified':False},
        'search_strategy':{'expanded':True,'candidate_source':'LOCATED_OFFICIAL_MEETING_QUOTES','same_project_verified':False},
        'execution_trace':{'mcp_tool':'council_context_pack','stages':[{'stage':'discovery_0','status':'PARTIAL'}]},
        'council_evidence':{'status':'PARTIAL','snapshot_id':'s1','items':[
            {'event_id':f'e{i}','text':'공식 발언'*20000,'source_url':'https://clik.nanet.go.kr/'+str(i)} for i in range(40)]}}

@pytest.mark.parametrize('unprotected_bulk',[False,True])
def test_compact_linked_review_survives_oversized_response(unprotected_bulk):
    original=payload()
    if unprotected_bulk:
        # Unknown structural arrays force the envelope-reduction path too.
        original['unknown_bulk']=[{'source_url':'https://clik.nanet.go.kr/'+('a'*300)} for _ in range(200)]
    before=copy.deepcopy(original)
    result=apply_budget(original,limit=30000)
    assert original==before
    assert size_of(result)<=30000
    assert result['status']=='PARTIAL'
    assert result['ready_for_submission'] is False
    assert result['linked_review']['budget']['discovered_candidates']==1
    assert result['linked_review']['ordinance']['discovered_candidates']==1
    assert result['linked_review']['same_project_verified'] is False
    assert result['linked_review']['legal_approval'] is False
    assert result['linked_review']['unresolved']
    relationship=result['linked_review']['relationships'][0]
    assert relationship['same_project_verified'] is False
    assert relationship['continuation']['tool']=='council_finance_context'
    assert result['search_strategy']['expanded'] is True
    assert result['execution_trace']['stages'][0]['status']=='PARTIAL'
    assert result['response_budget']['truncated'] is True
    assert result['response_budget']['reduced_count']>0

def test_compact_finance_recovery_is_schema_executable():
    from v3_reliability import compact_discovery
    row={'project_name':'문화예술 지원사업','fiscal_year':'2026','execution_date':'20261003',
         'local_government':'서울특별시 종로구','project_code':'p1','amount_unit':'SOURCE_CONFIRMATION_REQUIRED'}
    compact=compact_discovery('budget',{'term':'문화예술 지원사업'},{'status':'PARTIAL','items':[row]})
    args=compact['result']['items'][0]['recovery']['arguments']
    assert type(args['fiscal_year']) is int
    assert args['fiscal_year']==2026
    assert args['budget_stage']=='current'

def test_compact_ordinance_does_not_hide_document_failure():
    from v3_reliability import compact_discovery
    row={'document_id':'123','mst':'456','title':'문화예술 지원 조례','applicability_verified':False,
         'detail_error':{'code':'upstream_unavailable','meaning':'후보 발견과 원문 검증을 구분하세요.'}}
    compact=compact_discovery('ordinance',{'term':'문화예술 지원 조례'},{'status':'PARTIAL','items':[row]})
    item=compact['result']['items'][0]
    assert item['detail_error']['code']=='upstream_unavailable'
    assert item['applicability_verified'] is False
    assert item['recovery']['arguments']['reference']['document_id']=='123'


def test_compact_candidate_identity_index_survives_item_caps():
    from response_budget import apply_budget
    index = {'ordinance':[{'document_id':str(n),'title':f'가상{n}지원조례'} for n in range(2)],
             'budget':[{'project_code':str(n),'project_name':f'가상{n}지원사업','same_project_verified':False} for n in range(3)]}
    payload = {'status':'PARTIAL','linked_review':{'candidate_index':index,
               'relationships':[{'result':{'items':[{'text':'가나다 '*5000} for _ in range(3)]}}]},
               'unbounded':[{'oversized':'x'*50000} for _ in range(10)]}
    result=apply_budget(payload,30000)
    assert result['linked_review']['candidate_index']==index
