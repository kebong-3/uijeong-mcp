"""Saturated query traffic must not strand MCP discovery or local status."""
import asyncio
import json
import httpx
import public_server as P
import runtime_security as R


def test_discovery_works_when_all_query_transport_slots_are_busy():
    async def run():
        entered=asyncio.Event(); release=asyncio.Event(); count=0
        async def inner(scope,receive,send):
            nonlocal count
            body=json.loads((await receive())['body'])
            if body.get('method')=='tools/call':
                count+=1
                if count==8: entered.set()
                await release.wait()
            await R._public_reply(send,200,{'ok':True})
        inner.uijeong_public_readonly=True
        policy={'auth_mode':'public','hosts':['mcp.test'],'origins':[],'token':'','oauth':None}
        app=R.HTTPGuard(inner,policy,requests_per_minute=8)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://mcp.test') as c:
            tasks=[asyncio.create_task(c.post('/mcp',json={'method':'tools/call','params':{'name':'search'}})) for _ in range(8)]
            try:
                await asyncio.wait_for(entered.wait(),1)
                response=await asyncio.wait_for(c.post('/mcp',json={'method':'tools/list'}),.5)
                assert response.status_code==200
                # Heavy calls cannot spend the independent discovery quota.
                assert (await c.post('/mcp',json={'method':'tools/call'})).status_code==429
            finally:
                release.set()
                await asyncio.gather(*tasks)
    asyncio.run(run())


def test_status_bypasses_heavy_tool_gate_and_standard_search_obeys_it():
    async def run():
        entered=asyncio.Event(); release=asyncio.Event(); count=0
        async def busy(query:str)->dict:
            nonlocal count
            count+=1
            if count==3: entered.set()
            await release.wait()
            return {'status':'COMPLETE'}
        async def council_status(live:bool=False)->dict:
            return {'status':'COMPLETE','live':live}
        tasks=[asyncio.create_task(P.public_function(busy)(query=str(i))) for i in range(3)]
        await asyncio.wait_for(entered.wait(),1)
        standard=asyncio.create_task(P.standard_function(busy)(query='standard'))
        try:
            result=await asyncio.wait_for(P.public_function(council_status)(live=False),.5)
            assert result['status']=='COMPLETE'
            await asyncio.sleep(.01)
            assert count==3 and not standard.done()
        finally:
            release.set()
            await asyncio.gather(*tasks,standard)
    asyncio.run(run())


def test_standard_error_does_not_turn_into_empty_search(monkeypatch):
    async def slow(query:str)->dict:
        await asyncio.sleep(1)
    monkeypatch.setattr(P,'TOOL_TIMEOUT_SECONDS',.001)
    async def run():
        import pytest
        with pytest.raises(RuntimeError,match='PUBLIC_QUERY_TIMEOUT'):
            await P.standard_function(slow)(query='x')
        assert P._tool_semaphore()._value==3
    asyncio.run(run())
