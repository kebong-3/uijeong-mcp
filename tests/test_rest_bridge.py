"""REST bridge(/api/v1) 검사. 실제 SDK, 프로세스 내 HTTP, 외부 API 호출 없음.

다리가 지켜야 할 선: 새 기능이 아니라 같은 공개 서버로 가는 다른 입구라는 것.
허용목록·입력 상한·Host/Origin·본문 크기는 MCP 경로와 같아야 하고,
켜지 않으면 /api 경로는 이전처럼 404여야 한다.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_server as P
import rest_bridge as RB
import runtime_security as R

HOST = 'rest.example.test'


@pytest.fixture
def env(monkeypatch):
    import uijeong_mcp as U
    previous_mcp, previous_profile = U.mcp, U.PROFILE
    monkeypatch.setenv('UIJEONG_AUTH_MODE', 'public')
    monkeypatch.setenv('UIJEONG_PUBLIC_READONLY', 'true')
    monkeypatch.setenv('UIJEONG_ALLOWED_HOSTS', HOST)
    monkeypatch.setenv('UIJEONG_BIND_HOST', '0.0.0.0')
    monkeypatch.delenv('UIJEONG_REST_KEY', raising=False)
    monkeypatch.setenv('UIJEONG_REST_ENABLED', 'true')
    yield monkeypatch
    U.mcp, U.PROFILE = previous_mcp, previous_profile


def serve(check):
    """공개 서버를 실제와 같은 순서(HTTPGuard → PublicBoundary → RestBridge → MCP)로 띄워 check를 돈다."""
    async def run():
        server = P.build_server()
        raw = server.streamable_http_app()
        raw.uijeong_public_readonly = True
        app = R.secure_http_app(RB.RestBridge(raw, server, P.PUBLIC_TOOLS))
        async with raw.router.lifespan_context(raw):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                         base_url='https://' + HOST) as client:
                return await check(client)
    return asyncio.run(run())


def test_disabled_by_default_keeps_api_paths_404(env):
    env.delenv('UIJEONG_REST_ENABLED')

    async def check(client):
        assert (await client.get('/api/v1/tools')).status_code == 404
        assert (await client.post('/api/v1/tools/council_find_council', json={'query': '광주 서구'})).status_code == 404
    serve(check)


def test_index_and_listing_expose_exactly_the_public_allowlist(env):
    async def check(client):
        index = await client.get('/api/v1')
        assert index.status_code == 200 and index.json()['browser_cors'] is False
        assert index.json()['key_required'] is False
        listing = await client.get('/api/v1/tools')
        assert listing.status_code == 200
        rows = listing.json()['tools']
        assert {row['name'] for row in rows} == set(P.PUBLIC_TOOLS)
        assert len(rows) == 40
        assert all(isinstance(row['input_schema'], dict) for row in rows)
        assert listing.headers['cache-control'] == 'no-store'
    serve(check)


def test_rest_and_mcp_return_the_same_result(env):
    args = {'operation': 'change', 'arguments': {'before': '100', 'after': '120', 'unit': '천원'}}

    async def check(client):
        rest = await client.post('/api/v1/tools/budget_calculate', json=args)
        assert rest.status_code == 200
        body = rest.json()
        assert body['ok'] is True and body['tool'] == 'budget_calculate'
        mcp_headers = {'accept': 'application/json, text/event-stream', 'mcp-protocol-version': '2025-11-25'}
        await client.post('/mcp', headers=mcp_headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
        via_mcp = (await client.post('/mcp', headers=mcp_headers, json={'jsonrpc': '2.0', 'id': 2,
            'method': 'tools/call', 'params': {'name': 'budget_calculate', 'arguments': args}})).json()['result']
        rest_result, mcp_result = dict(body['result']), dict(via_mcp['structuredContent'])
        rest_receipt, mcp_receipt = rest_result.pop('mcp_receipt'), mcp_result.pop('mcp_receipt')
        assert rest_result == mcp_result, 'REST는 MCP와 같은 구조화 결과를 준다'
        # 호출마다 다른 것은 실행 기록(request_id·elapsed)뿐이며, 둘 다 같은 서버 래퍼를 거쳤다.
        assert rest_receipt['tool'] == mcp_receipt['tool'] == 'budget_calculate'
        assert rest_receipt['server_version'] == mcp_receipt['server_version']
        assert rest_receipt['request_id'] != mcp_receipt['request_id']
        assert '20000' in json.dumps(body['result'])
    serve(check)


def test_string_returning_tool_comes_back_structured(env):
    async def check(client):
        found = await client.post('/api/v1/tools/council_find_council', json={'query': '광주 서구'})
        assert found.status_code == 200 and found.json()['ok'] is True
        assert '062006' in json.dumps(found.json()['result'], ensure_ascii=False)
    serve(check)


@pytest.mark.parametrize('name', ['council_search_local', 'not_a_tool', 'council_find_council/extra', 'COUNCIL_FIND_COUNCIL'])
def test_tools_outside_the_allowlist_are_not_callable(env, name):
    async def check(client):
        response = await client.post('/api/v1/tools/' + name, json={'keyword': 'x'})
        assert response.status_code == 404
        assert response.json()['ok'] is False
    serve(check)


def test_method_and_body_errors_are_plain_http_errors(env):
    async def check(client):
        assert (await client.get('/api/v1/tools/council_find_council')).status_code == 405
        assert (await client.post('/api/v1/tools', json={})).status_code == 405
        assert (await client.post('/api/v1', json={})).status_code == 405
        bad = await client.post('/api/v1/tools/council_find_council', content=b'{not json',
                                headers={'content-type': 'application/json'})
        assert bad.status_code == 400 and bad.json()['code'] == 'INVALID_JSON'
        array = await client.post('/api/v1/tools/council_find_council', json=['광주 서구'])
        assert array.status_code == 400
        assert (await client.get('/api/v1/nothing')).status_code == 404
    serve(check)


def test_schema_violation_is_422_with_reason(env):
    async def check(client):
        response = await client.post('/api/v1/tools/council_find_council', json={'nope': 1})
        assert response.status_code == 422
        assert response.json()['code'] == 'INVALID_ARGUMENTS'
        assert 'query' in response.json()['message']
    serve(check)


def test_public_query_caps_apply_through_rest(env):
    async def check(client):
        response = await client.post('/api/v1/tools/council_evidence_bundle',
                                     json={'keyword': '경로당', 'council': '광주 서구', 'max_docs': 99})
        if response.status_code == 422:
            assert 'max_docs' in response.json()['message']
        else:
            body = response.json()
            assert body['ok'] is False and body['status'] == 'INVALID_INPUT'
    serve(check)


def test_browser_origins_and_foreign_hosts_are_still_rejected(env):
    async def check(client):
        foreign_origin = await client.get('/api/v1/tools', headers={'origin': 'https://somewhere.example'})
        assert foreign_origin.status_code == 403
        foreign_host = await client.get('/api/v1/tools', headers={'host': 'evil.example'})
        assert foreign_host.status_code == 403
        oversized = await client.post('/api/v1/tools/council_find_council', content=b'x' * 65537)
        assert oversized.status_code == 413
    serve(check)


def test_optional_key_locks_every_rest_path(env):
    key = 'k' * 32
    env.setenv('UIJEONG_REST_KEY', key)

    async def check(client):
        assert (await client.get('/api/v1')).status_code == 401
        assert (await client.get('/api/v1/tools', headers={'x-uijeong-key': 'wrong'})).status_code == 401
        listing = await client.get('/api/v1/tools', headers={'x-uijeong-key': key})
        assert listing.status_code == 200
        called = await client.post('/api/v1/tools/council_find_council', headers={'x-uijeong-key': key},
                                   json={'query': '광주 서구'})
        assert called.json()['ok'] is True
        # The key never reaches MCP: /mcp keeps its own (public) contract.
        assert (await client.get('/mcp')).status_code == 405
    serve(check)


def test_short_key_is_refused_at_startup(env):
    env.setenv('UIJEONG_REST_KEY', 'short')
    with pytest.raises(R.SecurityError):
        RB.RestBridge(object(), object(), P.PUBLIC_TOOLS)


def test_bridge_keeps_public_readonly_marker():
    class Inner:
        uijeong_public_readonly = True
    assert RB.RestBridge(Inner(), object(), ()).uijeong_public_readonly is True

    class Plain:
        pass
    assert RB.RestBridge(Plain(), object(), ()).uijeong_public_readonly is False


@pytest.mark.parametrize('raw,expected', [
    ((['t'], {'a': 1}), (False, {'a': 1})),
    ((['t'], None), (False, None)),
])
def test_normalize_tuple_results(raw, expected):
    blocks = [type('B', (), {'text': 'hello'})()]
    is_error, structured, text = RB.normalize((blocks, raw[1]))
    assert (is_error, structured) == expected and text == 'hello'


def test_normalize_parses_json_text_when_structured_missing():
    result = type('R', (), {'structuredContent': None, 'isError': True,
                            'content': [{'text': '{"status": "ERROR", "message": "x"}'}]})()
    assert RB.normalize(result) == (True, {'status': 'ERROR', 'message': 'x'}, '{"status": "ERROR", "message": "x"}')


def test_self_test_covers_rest_when_enabled(env):
    report = asyncio.run(P.self_test())
    assert report['status'] == 'PASS'
    assert report['checks']['rest_same_allowlist'] and report['checks']['rest_real_tool']
    assert report['checks']['rest_private_tool_not_callable']
