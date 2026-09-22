"""No upstream traffic: public policy, real ASGI guard and tool-boundary tests."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
from typing import Optional

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_security as R
import public_server as P


@pytest.fixture
def public_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith('UIJEONG_') or name == 'PORT':
            monkeypatch.delenv(name)
    monkeypatch.setenv('UIJEONG_AUTH_MODE', 'public')
    monkeypatch.setenv('UIJEONG_PUBLIC_READONLY', 'true')
    monkeypatch.setenv('UIJEONG_BIND_HOST', '0.0.0.0')
    monkeypatch.setenv('UIJEONG_ALLOWED_HOSTS', 'mcp.example.test')


def test_public_requires_explicit_ack(public_env, monkeypatch):
    monkeypatch.delenv('UIJEONG_PUBLIC_READONLY')
    with pytest.raises(R.SecurityError): R.http_policy()


def test_remote_public_requires_exact_hosts(public_env, monkeypatch):
    monkeypatch.delenv('UIJEONG_ALLOWED_HOSTS')
    with pytest.raises(R.SecurityError): R.http_policy()


@pytest.mark.parametrize('host', ['*', 'https://mcp.example.test', 'a@b', 'a b'])
def test_bad_public_hosts(public_env, monkeypatch, host):
    monkeypatch.setenv('UIJEONG_ALLOWED_HOSTS', host)
    with pytest.raises(R.SecurityError): R.http_policy()


def test_none_alias_does_not_use_legacy_token(public_env, monkeypatch):
    monkeypatch.setenv('UIJEONG_AUTH_MODE', 'none')
    monkeypatch.setenv('UIJEONG_BEARER_TOKEN', 'dummy-legacy-secret-not-production')
    policy = R.http_policy()
    assert policy['auth_mode'] == 'public' and not policy['token'] and policy['oauth'] is None
    assert 'dummy-legacy' not in json.dumps(R.auth_diagnostics())


def test_unmarked_app_cannot_be_public(public_env):
    async def app(scope, receive, send): pass
    with pytest.raises(R.SecurityError): R.HTTPGuard(app)


def test_real_guard_no_auth_and_rejections(public_env):
    async def inner(scope, receive, send):
        assert R.REQUEST_SCOPE.get() == 'public-readonly-v1'
        await R._public_reply(send, 200, {'ok': True})
    inner.uijeong_public_readonly = True
    app = R.HTTPGuard(inner)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://mcp.example.test') as c:
            assert (await c.post('/mcp', json={})).status_code == 200
            assert (await c.get('/mcp')).status_code == 405
            assert (await c.get('/healthz')).status_code == 200
            assert (await c.post('/mcp', content=b'x' * 65537)).status_code == 413
            assert (await c.post('/mcp', json={}, headers={'origin':'https://bad.example'})).status_code == 403
            assert (await c.post('/mcp', json={}, headers={'host':'bad.example'})).status_code == 403
        assert R.REQUEST_SCOPE.get() == 'local'
    asyncio.run(run())


def test_public_global_rate_limit(public_env):
    async def inner(scope, receive, send): await R._public_reply(send, 200, {'ok': True})
    inner.uijeong_public_readonly = True
    app=R.HTTPGuard(inner, requests_per_minute=1)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://mcp.example.test') as c:
            assert (await c.post('/mcp', json={})).status_code == 200
            assert (await c.post('/mcp', json={})).status_code == 429
    asyncio.run(run())


def test_three_concurrent_then_recover(public_env):
    async def run():
        entered=asyncio.Event(); release=asyncio.Event(); count=0
        async def inner(scope, receive, send):
            nonlocal count
            count+=1
            if count==3: entered.set()
            await release.wait()
            await R._public_reply(send, 200, {'ok': True})
        inner.uijeong_public_readonly=True
        app=R.HTTPGuard(inner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://mcp.example.test') as c:
            tasks=[asyncio.create_task(c.post('/mcp',json={})) for _ in range(3)]
            await asyncio.wait_for(entered.wait(), 1)
            assert (await c.post('/mcp',json={})).status_code == 503
            release.set()
            assert all(x.status_code==200 for x in await asyncio.gather(*tasks))
            assert (await c.post('/mcp',json={})).status_code == 200
    asyncio.run(run())


def test_public_cannot_read_existing_local_snapshot(public_env, tmp_path):
    store=R.SnapshotStore(tmp_path/'state.sqlite3',scope='official-evidence-v2',bind_request_scope=True)
    ident=store.put({'public_source':'test'}, source_kind='CLIK')
    context=R.REQUEST_SCOPE.set('public-readonly-v1')
    try:
        assert store.get(ident) is None
        own=store.put({'public_source':'test2'}, source_kind='CLIK')
        assert store.get(own)
    finally:R.REQUEST_SCOPE.reset(context)
    assert store.get(ident) and store.get(own) is None


def test_private_payload_storage_stays_forbidden(public_env, tmp_path):
    store=R.SnapshotStore(tmp_path/'s.db')
    with pytest.raises(R.SecurityError):store.put({'draft':'test'},source_kind='USER_PROVIDED')


def test_legacy_remote_local_still_fails(public_env, monkeypatch):
    monkeypatch.setenv('UIJEONG_AUTH_MODE','local')
    with pytest.raises(R.SecurityError):R.http_policy()


def test_protected_bearer_still_requires_token(public_env, monkeypatch):
    monkeypatch.setenv('UIJEONG_AUTH_MODE','bearer')
    with pytest.raises(R.SecurityError):R.http_policy()
    monkeypatch.setenv('UIJEONG_BEARER_TOKEN','x'*40)
    assert R.http_policy()['token']=='x'*40


def test_tool_signature_and_limit_before_call():
    called=[]
    async def tool(max_docs:int=6, query:Optional[str]=None)->dict:
        called.append(True)
        return {'status':'COMPLETE'}
    wrapped=P.public_function(tool)
    assert inspect.signature(wrapped)==inspect.signature(tool)
    assert asyncio.run(wrapped(max_docs=7))['code']=='PUBLIC_QUERY_LIMIT'
    assert not called
    assert asyncio.run(wrapped())['status']=='COMPLETE'


def test_tool_exception_and_secret_redaction(monkeypatch):
    monkeypatch.setenv('CLIK_API_KEY','synthetic-secret-1234')
    async def good():return {'status':'COMPLETE','nested':['synthetic-secret-1234']}
    assert 'synthetic-secret' not in json.dumps(asyncio.run(P.public_function(good)()))
    async def bad():raise RuntimeError('synthetic-secret-1234')
    result=asyncio.run(P.public_function(bad)())
    assert result['status']=='ERROR' and 'synthetic-secret' not in json.dumps(result)


def test_tool_timeout(monkeypatch):
    monkeypatch.setattr(P,'TOOL_TIMEOUT_SECONDS',0.001)
    async def slow():await asyncio.sleep(1)
    assert asyncio.run(P.public_function(slow)())['code']=='PUBLIC_QUERY_TIMEOUT'


def test_no_document_input_or_local_archive_tools():
    assert len(P.PUBLIC_TOOLS)==10
    assert not set(P.PUBLIC_TOOLS)&{'council_search_local','council_analyze_text','council_review_answer','council_build_issue_card'}


def test_legacy_deep_search_is_rejected_before_call():
    called=[]
    async def tool(depth:str='보통')->dict:
        called.append(True)
        return {'status':'COMPLETE'}
    wrapped=P.public_function(tool)
    assert asyncio.run(wrapped(depth='깊게'))['code']=='PUBLIC_QUERY_LIMIT'
    assert not called
    assert asyncio.run(wrapped())['status']=='COMPLETE'
