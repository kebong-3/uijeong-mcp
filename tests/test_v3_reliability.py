"""Offline regression tests. Synthetic concurrency is not production capacity proof."""
import asyncio
import types

import pytest
import v3_reliability as V
import legal_context as L
import finance_context as F
import public_data_discovery as D
import council_extensions as C


@pytest.fixture(autouse=True)
def clean_v3_state():
    V._CACHE.clear()
    V._FLIGHTS.clear()
    yield
    V._CACHE.clear()
    V._FLIGHTS.clear()


@pytest.mark.parametrize('statuses,expected',[
    (['COMPLETE','EMPTY'],'COMPLETE'),
    (['COMPLETE','NOT_CONFIGURED'],'PARTIAL'),
    (['COMPLETE','ERROR'],'PARTIAL'),
    (['EMPTY','ERROR'],'PARTIAL'),
    (['ERROR','ERROR'],'ERROR'),
    (['EMPTY','EMPTY'],'EMPTY'),
    (['SKIPPED','COMPLETE'],'COMPLETE'),
    (['NOT_CONFIGURED'],'PARTIAL'),
])
def test_layer_state_is_truthful(statuses,expected):
    assert V.aggregate_status({str(i):{'status':s} for i,s in enumerate(statuses)})==expected


@pytest.mark.parametrize('value,expected',[(None,None),('',None),('NaN',None),('Infinity',None),(True,None),('1,234',1234),('9007199254740993',9007199254740993),('0',0)])
def test_money_parsing(value,expected):
    assert V.number(value)==expected


def test_missing_expenditure_does_not_mean_zero_percent():
    import uijeong_mcp  # installs reviewed v3 hooks against the actual backend
    row=F._public_row({'bdg_cash_amt':'100000000','ep_amt':None})
    assert row['execution_rate_percent'] is None
    assert F._public_row({'bdg_cash_amt':'100','ep_amt':'0'})['execution_rate_percent']==0


@pytest.mark.parametrize('other',['서구','인천광역시 서구','부산광역시 서구','경기도 가평군'])
def test_foreign_or_ambiguous_jurisdiction_is_not_seogu(other):
    assert not V.finance_belongs({'laf_hg_nm':other},'광주 서구')


def test_historical_alias_exact_match():
    assert V.finance_belongs({'laf_hg_nm':'광주광역시서구'},'전남광주통합특별시 서구의회')
    assert V.law_jurisdiction([{'jurisdiction':'경기도 가평군'},{'jurisdiction':'광주광역시 서구'}],'광주 서구')[0]==[{'jurisdiction':'광주광역시 서구'}]


@pytest.mark.parametrize('start,end',[('2026-02-30','2026-03-01'),('2026-10-01','2026-09-01'),('tomorrow','2026-09-01')])
def test_invalid_period(start,end):
    with pytest.raises(ValueError):
        V.valid_period(start,end)


def test_discovery_error_codes_are_not_values():
    payload={'response':{'header':{'resultCode':'00'},'body':{'items':[{'dataNm':'인구현황','orgNm':'공개기관','dataId':'30'}]}}}
    result=V.parse_discovery(payload)
    assert result['status']=='COMPLETE'
    assert result['items'][0]['actual_values_fetched'] is False
    assert V.parse_discovery({'response':{'header':{'resultCode':'30'}}})['status']=='ERROR'


def test_unknown_discovery_schema_is_not_empty():
    result=V.parse_discovery({'unexpected':{'value':'private-test-value'}})
    assert result['status']=='ERROR'
    assert 'private-test-value' not in str(result)
    assert V.parse_discovery({'items':[],'totalCount':0})['status']=='EMPTY'


@pytest.mark.parametrize('url',['http://www.data.go.kr/x','https://evil.test/x','https://www.data.go.kr/x?serviceKey=secret','https://u:p@data.go.kr/x'])
def test_discovery_links_are_safe(url):
    assert V.safe_url(url,'data.go.kr') is None


def test_40_identical_simultaneous_calls_share_one_execution():
    calls=[]
    async def lookup(query:str):
        calls.append(query)
        await asyncio.sleep(.02)
        return {'status':'COMPLETE','items':[{'value':'official-synthetic'}]}
    async def run():
        results=await asyncio.gather(*(V.run_public(lookup,(),{'query':'same'}) for _ in range(40)))
        assert len(calls)==1
        assert len({r['mcp_receipt']['request_id'] for r in results})==40
        assert sum(r['mcp_receipt']['result_reuse']=='coalesced' for r in results)==39
        assert all(r['mcp_receipt']['server_version']=='3.0.0-public.1' for r in results)
        cached=await V.run_public(lookup,(),{'query':'same'})
        assert cached['mcp_receipt']['result_reuse']=='short_cache'
        results[0]['items'].clear()
        assert cached['items']
    asyncio.run(run())


def test_partial_and_error_results_are_not_cached():
    calls=[]
    async def lookup():
        calls.append(1)
        return {'status':'PARTIAL'}
    async def run():
        await V.run_public(lookup,(),{})
        await V.run_public(lookup,(),{})
    asyncio.run(run())
    assert len(calls)==2 and not V._CACHE


def test_cache_enforces_entry_and_byte_limits(monkeypatch):
    monkeypatch.setattr(V,'CACHE_ENTRIES',3)
    monkeypatch.setattr(V,'CACHE_BYTES',1000)
    async def lookup(query:str):
        return {'status':'COMPLETE','text':'x'*300,'query':query}
    async def run():
        for i in range(8):
            await V.run_public(lookup,(),{'query':str(i)})
    asyncio.run(run())
    assert len(V._CACHE)<=3
    assert sum(row[1] for row in V._CACHE.values())<=1000


def test_cancelled_follower_does_not_cancel_shared_lookup():
    calls=[]
    async def lookup(query:str):
        calls.append(query)
        await asyncio.sleep(.03)
        return {'status':'COMPLETE'}
    async def run():
        first=asyncio.create_task(V.run_public(lookup,(),{'query':'same'}))
        second=asyncio.create_task(V.run_public(lookup,(),{'query':'same'}))
        await asyncio.sleep(.005)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second)['status']=='COMPLETE'
    asyncio.run(run())
    assert len(calls)==1


def test_legal_query_is_local_and_national_search_is_separate(monkeypatch):
    monkeypatch.setenv('LAW_OC','synthetic')
    calls=[]
    async def request(endpoint,params):
        calls.append(params)
        if params['target']=='law':
            return {'LawSearch':{'totalCnt':'1','law':[{'법령ID':'1','법령일련번호':'2','법령명한글':'공무원 후생복지에 관한 규정'}]}}
        return {'OrdinSearch':{'totalCnt':'2','ordin':[
            {'자치법규ID':'3','자치법규일련번호':'4','자치법규명':'서구 후생복지 조례','지자체기관명':'전남광주통합특별시 서구'},
            {'자치법규ID':'5','자치법규일련번호':'6','자치법규명':'가평 후생복지 조례','지자체기관명':'경기도 가평군'}]}}
    monkeypatch.setattr(L,'_request',request)
    result=asyncio.run(V.legal_context('공무원 후생복지','전남광주통합특별시 서구',False))
    assert len(result['ordinances'])==1
    assert result['ordinances'][0]['jurisdiction']=='전남광주통합특별시 서구'
    assert result['legal_conclusion_verified'] is False
    assert all(x['query']=='공무원 후생복지' for x in calls if x['target']=='law')
    assert all('서구' in x['query'] for x in calls if x['target']=='ordin')


def test_failed_layer_preserves_report_without_inventing_question(monkeypatch):
    async def empty(*a,**k): return {'status':'EMPTY','items':[]}
    async def fail(*a,**k): raise RuntimeError('synthetic failure')
    monkeypatch.setattr(C,'_bill_context',fail)
    monkeypatch.setattr(C,'_member_discovery',empty)
    monkeypatch.setattr(C,'_policy_context',empty)
    async def evidence(**kwargs):
        if kwargs['mode']=='발언':
            return {'status':'COMPLETE','items':[{'speech':{'role':'executive','act':'report','text':'휴라운지 운영 보고'}}]}
        return {'status':'EMPTY','items':[]}
    backend=types.SimpleNamespace(pick_council=lambda q:('062006','광주 서구',None),council_evidence_bundle=evidence)
    result=asyncio.run(V.context_pack(backend,'휴라운지',include_legal=False,include_finance=False,max_docs=1))
    assert result['status']=='PARTIAL'
    assert result['council_evidence']['items']==[]
    assert result['report_mentions']['items']
    assert result['related_bills']['status']=='ERROR'
    assert result['ready_for_submission'] is False


def test_finance_capped_nonlocal_page_is_partial_not_empty(monkeypatch):
    monkeypatch.setenv('LOFIN_API_KEY','synthetic')
    async def request(params):
        return {'result_code':'INFO-000','total_count':2000,'rows':[{'laf_hg_nm':'부산광역시 서구','fyr':'2026'}]}
    monkeypatch.setattr(F,'_request',request)
    result=asyncio.run(V.finance_context('빈집','광주 서구',2026,5))
    assert result['status']=='PARTIAL'
    assert result['items']==[]
    assert result['coverage']['has_unread_pages'] is True
