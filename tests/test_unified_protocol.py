"""Real anonymous Streamable HTTP smoke; deterministic data, no upstream network."""
import asyncio
import json
import sys
from pathlib import Path
import httpx
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import public_server as P
import runtime_security as R


def unpack(result):
    if isinstance(result.get('structuredContent'),dict):return result['structuredContent']
    return json.loads(next(b['text'] for b in result['content'] if b['type']=='text'))

@pytest.fixture
def env(monkeypatch):
    import uijeong_mcp as U
    previous_mcp, previous_profile = U.mcp, U.PROFILE
    monkeypatch.setenv('UIJEONG_AUTH_MODE','public')
    monkeypatch.setenv('UIJEONG_PUBLIC_READONLY','true')
    monkeypatch.setenv('UIJEONG_ALLOWED_HOSTS','unified.example.test')
    monkeypatch.setenv('UIJEONG_BIND_HOST','0.0.0.0')
    yield
    U.mcp, U.PROFILE = previous_mcp, previous_profile


def test_three_domains_over_real_anonymous_http(env):
    async def run():
        server=P.build_server()
        await P.verify_surface(server)
        raw=server.streamable_http_app()
        raw.uijeong_public_readonly=True
        app=R.secure_http_app(raw)
        headers={'accept':'application/json, text/event-stream','mcp-protocol-version':'2025-11-25'}
        async with raw.router.lifespan_context(raw):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://unified.example.test',headers=headers) as a, httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://unified.example.test',headers=headers) as b:
                async def rpc(client,method,params):
                    response=await client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':method,'params':params})
                    assert response.status_code==200,response.text
                    body=response.json()
                    assert 'error' not in body,body
                    return body['result']
                for client in (a,b):
                    init=await rpc(client,'initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'offline-smoke','version':'1'}})
                    assert init['protocolVersion']
                listing=await rpc(a,'tools/list',{})
                names={t['name'] for t in listing['tools']}
                assert names==set(P.PUBLIC_TOOLS)
                assert len(names)==40
                assert {'council_find_council','budget_calculate','ordinance_guide'}<=names
                calls=[('local_workflow_plan',{'question':'경로당 예산 조회','jurisdiction':'광주 서구','fiscal_year':2026}),('council_find_council',{'query':'광주 서구'}),('budget_calculate',{'operation':'change','arguments':{'before':'100','after':'120','unit':'천원'}}),('ordinance_guide',{})]
                for name,args in calls:
                    result=await rpc(a,'tools/call',{'name':name,'arguments':args})
                    assert not result.get('isError'),result
                    assert len(json.dumps(result,ensure_ascii=False))<100_000
                    assert unpack(result)
                # Two unrelated clients perform different calculations without session state.
                results=await asyncio.gather(*(rpc(client,'tools/call',{'name':'budget_calculate','arguments':{'operation':'change','arguments':{'before':'100','after':after,'unit':'천원'}}}) for client,after in [(a,'120'),(b,'130')]))
                assert '20000' in json.dumps(unpack(results[0]))
                assert '30000' in json.dumps(unpack(results[1]))
                bad=await rpc(b,'tools/call',{'name':'council_search_local','arguments':{'keyword':'x'}})
                assert bad.get('isError')
    asyncio.run(run())


def test_failed_and_stalled_upstream_are_errors(env,monkeypatch):
    import integrated_budget as B
    async def run():
        async def failed(*args,**kwargs):return {'status':'ERROR','message':'mock upstream failure'}
        monkeypatch.setattr(B,'call',failed)
        server=P.build_server()
        result=await server.call_tool('budget_fetch_api',{'api_id':'test','params':{}})
        text=str(result)
        assert 'ERROR' in text and 'EMPTY' not in text
        async def stalled():await asyncio.sleep(10)
        stalled.__name__='stability_stall_probe'
        monkeypatch.setattr(P,'TOOL_TIMEOUT_SECONDS',0.01)
        answer=await P.public_function(stalled)()
        assert answer['status']=='ERROR' and answer['code']=='PUBLIC_QUERY_TIMEOUT'
    asyncio.run(run())


def test_mocked_source_failure_over_http(env,monkeypatch):
    import integrated_budget as B
    import integrated_ordinance as O
    async def failure(*args,**kwargs): return {'status':'ERROR','message':'upstream unavailable'}
    monkeypatch.setattr(B,'call',failure)
    class BrokenLaw:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def search(self,*args,**kwargs):raise ValueError('upstream credentials must not leak')
    monkeypatch.setattr(O,'LawClient',BrokenLaw)
    async def run():
        server=P.build_server();raw=server.streamable_http_app();raw.uijeong_public_readonly=True
        async with raw.router.lifespan_context(raw):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(R.secure_http_app(raw)),base_url='https://unified.example.test',headers={'accept':'application/json, text/event-stream'}) as client:
                for name,args in [('budget_fetch_api',{'api_id':'test','params':{}}),('ordinance_search',{'query':'테스트'})]:
                    response=await client.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
                    assert response.status_code==200
                    result=response.json()['result']
                    assert result.get('isError') is True
                    assert unpack(result)['status'] in ('ERROR','unavailable')
                    assert 'upstream credentials must not leak' not in response.text
    asyncio.run(run())


def test_integrated_boundary_compact_errors_redaction_and_timeout(monkeypatch):
    import integrated_transport as T
    monkeypatch.setenv('LAW_API_OC','fixture-private-credential-unique')
    async def run():
        async def medium():return {'status':'retrieved','text':'가'*6000}
        result=await T.wrap(medium)()
        assert len(result.content[0].text)<200
        assert len(result.structuredContent['text'])==6000
        async def oversized():return {'status':'retrieved','text':'가'*31000}
        result=await T.wrap(oversized)()
        assert result.isError and result.structuredContent['status']=='OUTPUT_LIMIT'
        assert result.structuredContent['evidence_returned'] is False
        for status in ('ERROR','unavailable','TIMEOUT','NOT_CONFIGURED'):
            async def failed():return {'status':status}
            assert (await T.wrap(failed)()).isError
        async def leaks():raise RuntimeError('https://example.test/?OC=fixture-private-credential-unique')
        result=await T.wrap(leaks)()
        assert result.isError
        assert 'fixture-private-credential-unique' not in str(result)
        async def stalled():await asyncio.sleep(1)
        monkeypatch.setattr(T,'TIMEOUT_SECONDS',.01)
        result=await T.wrap(stalled)()
        assert result.isError and result.structuredContent['status']=='TIMEOUT'
        def sync_result():return {'status':'PLAN_ONLY','retrieved':False}
        assert not (await T.wrap(sync_result)()).isError
    asyncio.run(run())
