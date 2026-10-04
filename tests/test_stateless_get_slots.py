"""Regression: idle GET SSE connections must never consume query slots."""
import asyncio
import httpx
import runtime_security as R


def test_idle_get_never_reaches_stream_or_blocks_post():
    async def run():
        reached = []
        async def inner(scope, receive, send):
            reached.append(scope['method'])
            if scope['method'] == 'GET':
                await asyncio.Event().wait()  # SDK standalone SSE stays open.
            await R._public_reply(send, 200, {'ok': True})
        app = R.PublicBoundary(inner, max_concurrent=8, queue_timeout=.01)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://test') as client:
            for _ in range(16):
                response = await asyncio.wait_for(client.get('/mcp', headers={'accept':'text/event-stream'}), .5)
                assert response.status_code == 405
                assert response.headers['allow'] == 'POST, DELETE'
            assert app.active == 0 and app.waiting == 0
            assert app._slots._value == 8 and reached == []
            assert (await client.post('/mcp', json={})).status_code == 200
            assert (await client.delete('/mcp')).status_code == 200
        assert reached == ['POST', 'DELETE'] and app.active == 0
    asyncio.run(run())


def test_get_rejection_does_not_wait_for_a_busy_query_slot():
    async def run():
        entered, finish = asyncio.Event(), asyncio.Event()
        async def inner(scope, receive, send):
            entered.set()
            await finish.wait()
            await R._public_reply(send, 200, {'ok':True})
        app=R.PublicBoundary(inner, max_concurrent=1, queue_timeout=.01)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://test') as client:
            task=asyncio.create_task(client.post('/mcp', json={}))
            await asyncio.wait_for(entered.wait(), .5)
            try:
                response=await asyncio.wait_for(client.get('/mcp'), .5)
                assert response.status_code == 405 and app.active == 1
            finally:
                finish.set()
                assert (await task).status_code == 200
        assert app.active == 0 and app._slots._value == 1
    asyncio.run(run())
