import asyncio
import os
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uijeong_mcp as U

BODY='<b>○김가상 위원</b> 성인지 예산 교육은 어떻게 합니까?<br>○기획과장 이가상: 10월까지 자료를 제출하겠습니다.<br>'
REPORT='<b>○기획과장 이가상</b> 성인지 예산 교육의 운영현황을 보고드리겠습니다. 참여자는 10명입니다.'

def meta(doc='D1',body=BODY,name='기획위원회',date='20250101'):
    return dict(DOCID=doc,MINTS_HTML=body,RASMBLY_ID='062006',RASMBLY_NM='가상서구의회',
                RASMBLY_NUMPR='9',RASMBLY_SESN='300',MINTS_ODR='1',MTGNM=name,MTG_DE=date)

@pytest.fixture
def fake(monkeypatch,tmp_path):
    U.clik._cache.clear()
    monkeypatch.setattr(U,'API_KEY','TEST-ONLY')
    from runtime_security import SQLiteBudget
    monkeypatch.setattr(U.clik,'_budget',SQLiteBudget(tmp_path/'budget.db',1000))
    data={'rows':[meta()], 'calls':[], 'fail':False}
    async def raw(path,params):
        data['calls'].append(params.copy())
        if data['fail']:raise U.ClikError('simulated failure')
        if params.get('displayType')=='detail':
            return [{'RESULT_CODE':'SUCCESS',**next(r for r in data['rows'] if r['DOCID']==params['docid'])}]
        start=params.get('startCount',0)
        return [{'RESULT_CODE':'SUCCESS','TOTAL_COUNT':len(data['rows']),
                 'LIST':[{'ROW':r} for r in data['rows'][start:start+100]]}]
    monkeypatch.setattr(U.clik,'_raw_get',raw)
    return data

def run(coro):return asyncio.run(coro)

def test_report_mode_vs_qa(fake):
    fake['rows']=[meta(body=REPORT)]
    found=run(U.council_evidence_bundle('성인지예산',source='clik',mode='발언'))
    assert found['total_items']==1
    qa=run(U.council_evidence_bundle('성인지예산',source='clik',mode='질의답변'))
    assert qa['total_items']==0

def test_committee_before_detail_limit(fake):
    fake['rows']=[meta('OTHER',name='다른위원회'),meta('TARGET')]
    r=run(U.council_evidence_bundle('성인지예산',source='clik',committee='기획',max_docs=1))
    assert r['total_items']==1
    assert [c['docid'] for c in fake['calls'] if c.get('displayType')=='detail']==['TARGET']

def test_error_not_empty(fake):
    fake['fail']=True
    r=run(U.council_evidence_bundle('성인지예산',source='clik'))
    assert r['status']=='ERROR' and r['errors']

def test_invalid_dates_no_call(fake):
    r=run(U.council_evidence_bundle('성인지예산',source='clik',date_from='2026-09-17',date_to='2023-09-17'))
    assert r['status']=='INVALID_INPUT' and not fake['calls']

def test_snapshot_reuse_and_binding(fake):
    fake['rows']=[meta(body=BODY*7)]
    first=run(U.council_evidence_bundle('성인지예산',source='clik',limit=2))
    count=len(fake['calls'])
    nxt=run(U.council_evidence_bundle('성인지예산',source='clik',limit=2,snapshot_id=first['snapshot_id'],item_offset=2))
    assert nxt['items'] and len(fake['calls'])==count
    bad=run(U.council_evidence_bundle('다른검색어',source='clik',snapshot_id=first['snapshot_id']))
    assert bad['status']=='INVALID_INPUT'

def test_long_source_complete(fake):
    text='가나다 '*4000+'끝표식'
    fake['rows']=[meta(body='<b>○기획과장 이가상</b>'+text)]
    result=[];turn=char=0
    for _ in range(100):
        page=run(U.council_read_source('D1',start_turn=turn,start_char=char,max_chars=1000))
        result.extend(t['text'] for t in page['turns'])
        if page['next_start_turn'] is None:break
        turn=page['next_start_turn'];char=page['next_start_char']
    assert ''.join(result)==text

def test_foreign_url_rejected_without_fetch(fake):
    result=run(U.council_read_source('https://evil.example/record/recordView.do?key=abc'))
    assert result['status']=='INVALID_INPUT' and not fake['calls']

def test_partial_second_list_page_preserves_first(fake,monkeypatch):
    async def get(path,**params):
        if params['startCount']>=100:raise U.ClikError('page2 failure')
        return {'TOTAL_COUNT':200,'LIST':[{'ROW':meta(str(i))} for i in range(100)]}
    monkeypatch.setattr(U.clik,'get',get)
    async def collect():
        rows,total=await U.list_minutes('topic','062006',want=150)
        return rows,total,dict(U.list_state())
    rows,total,state=run(collect())
    assert len(rows)==100 and total==200 and state['next_pos']==100 and state['errors']

def test_period_each_year(fake):
    r=run(U.council_period_review('성인지예산',council='수원시',years=3,as_of='2026-09-17',include_current_year=False,max_docs_per_year=1))
    assert [x['meeting_year'] for x in r['results']]==[2023,2024,2025]
    assert r['year_basis']=='회의연도'

def test_prepare_pack_grounded(fake,monkeypatch):
    async def empty(page):return []
    monkeypatch.setattr(U.site,'list_page',empty)
    result=run(U.council_prepare_pack('성인지예산',max_docs=1))
    assert result['briefing'] and result['followup_ledger']
    assert '후속 증빙 미확인' in str(result)

def test_read_source_never_leaks_credential_url(fake):
    fake['rows'][0]['ORGINL_FILE_URL']='https://clik.nanet.go.kr/openapi/minutes.do?key=PRIVATE-TEST-VALUE'
    page=run(U.council_read_source('D1'))
    assert 'PRIVATE-TEST-VALUE' not in str(page)
    assert page['provenance']['source_url_status']=='NOT_AVAILABLE'
    assert page['provenance']['body_url_status']=='FETCHED'

def test_storage_failure_has_recovery_refs(fake,monkeypatch):
    def fail(*a,**k):
        from runtime_security import SecurityError
        raise SecurityError('보관 한도 초과')
    monkeypatch.setattr(U.V2_SERVICES['snapshots'],'put',fail)
    r=run(U.council_evidence_bundle('성인지예산',source='clik'))
    assert r['status']=='PARTIAL' and r['snapshot_id'] is None
    assert r['candidate_refs'][0]['ref']=='D1' and r['recovery']

def test_internal_followup_items_not_duplicated_on_wire(fake):
    r=run(U.council_evidence_bundle('성인지예산',source='clik'))
    assert 'followup_items' not in r
    payload=U.V2_SERVICES['snapshots'].get(r['snapshot_id'])
    assert payload['followup_items']

def test_all_sources_failure_is_error(fake,monkeypatch):
    fake['fail']=True
    async def fail(page):raise U.SiteBlocked('blocked')
    monkeypatch.setattr(U.site,'list_page',fail)
    result=run(U.council_evidence_bundle('성인지예산'))
    assert result['status']=='ERROR'
