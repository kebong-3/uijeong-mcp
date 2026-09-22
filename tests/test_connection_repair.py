"""Isolated private OAuth HTTP tests. Synthetic secrets; no remote services."""
import asyncio
import hashlib
import logging
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from uvicorn.logging import AccessFormatter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_security as R
from oauth_local import LocalOAuthConfig, LocalOAuthServer, SCOPE, password_hash, _b64
ISSUER = 'https://uijeong.example'
RESOURCE = ISSUER + '/mcp'
REDIRECT = 'https://chatgpt.com/connector_platform_oauth_redirect'
PASSWORD = 'SYNTHETIC-operator-password-123456789'
PASSWORD_HASH = password_hash(PASSWORD, b'1234567890123456')
VERIFIER = 'A' * 43
CHALLENGE = _b64(hashlib.sha256(VERIFIER.encode()).digest())

def setup(tmp_path):
    now = [1000.0]
    cfg = LocalOAuthConfig(ISSUER, RESOURCE, b'SYNTHETIC-SIGNING-KEY-DO-NOT-USE', PASSWORD_HASH, tmp_path/'oauth.sqlite3')
    async def inner(scope, receive, send):
        from starlette.responses import JSONResponse
        await JSONResponse({'identity': R.REQUEST_SCOPE.get()})(scope, receive, send)
    policy = dict(hosts=['uijeong.example'], origins=[ISSUER], token='', auth_mode='oauth_local', oauth=cfg)
    guard = R.HTTPGuard(inner, policy)
    guard.oauth_server.clock = lambda: now[0]
    return guard, cfg, now

def client(guard):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=guard), base_url=ISSUER, follow_redirects=False)

async def register(c, method='none'):
    response = await c.post('/oauth/register', json={'redirect_uris':[REDIRECT], 'client_name':'Synthetic Client', 'token_endpoint_auth_method':method})
    assert response.status_code == 201, response.text
    return response.json()

async def flow(c, registration):
    q = dict(client_id=registration['client_id'], redirect_uri=REDIRECT, response_type='code', scope=SCOPE, resource=RESOURCE, state='synthetic-state', code_challenge=CHALLENGE, code_challenge_method='S256')
    response = await c.get('/oauth/authorize', params=q)
    assert response.status_code == 200, response.text
    fields = dict(re.findall(r'name="(flow|csrf)" value="([A-Za-z0-9_-]+)"', response.text))
    assert set(fields) == {'flow','csrf'}
    return fields

async def code(c, registration):
    fields = await flow(c, registration)
    response = await c.post('/oauth/approve', headers={'Origin':ISSUER}, data=dict(fields,password=PASSWORD,decision='approve'))
    assert response.status_code == 303, response.text
    params = parse_qs(urlsplit(response.headers['location']).query)
    assert params['iss'] == [ISSUER] and params['state'] == ['synthetic-state']
    return params['code'][0]

def exchange_data(registration, value):
    data = dict(client_id=registration['client_id'], code=value, grant_type='authorization_code', resource=RESOURCE, redirect_uri=REDIRECT, code_verifier=VERIFIER)
    if registration['token_endpoint_auth_method'] == 'client_secret_post':
        data['client_secret'] = registration['client_secret']
    return data

async def access(c, registration):
    value = await code(c, registration)
    kwargs = {}
    if registration['token_endpoint_auth_method'] == 'client_secret_basic':
        kwargs['auth'] = httpx.BasicAuth(registration['client_id'], registration['client_secret'])
    response = await c.post('/oauth/token', data=exchange_data(registration, value), **kwargs)
    assert response.status_code == 200, response.text
    return response.json()

def test_uvicorn_formatter_preserves_five_arguments_and_redacts(monkeypatch):
    secret = 'synthetic-secret-keep-private'
    monkeypatch.setenv('CLIK_API_KEY', secret)
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 1, '%s - "%s %s HTTP/%s" %d', ('127.0.0.1:0','POST','/mcp?key='+secret+'&code=one-time-code','1.1',401),None)
    R.SecretFilter().filter(record)
    assert len(record.args) == 5 and record.args[-1] == 401
    output = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert '401' in output and secret not in output and 'one-time-code' not in output

def test_private_guard_and_discovery(tmp_path):
    async def run():
        guard, cfg, now = setup(tmp_path)
        async with client(guard) as c:
            response = await c.post('/mcp', json={})
            assert response.status_code == 401
            assert cfg.metadata_url in response.headers['www-authenticate']
            for path in ('/.well-known/oauth-protected-resource',cfg.metadata_path):
                assert (await c.get(path)).json()['resource'] == RESOURCE
            meta = (await c.get('/.well-known/oauth-authorization-server')).json()
            assert meta['code_challenge_methods_supported'] == ['S256']
            assert meta['authorization_response_iss_parameter_supported'] is True
            assert (await c.get('/healthz')).status_code == 200
            assert (await c.get('/')).status_code == 200
            assert (await c.post('/mcp', headers={'Authorization':'Bearer '+'old-static-token'*4})).status_code == 401
            assert (await c.get('/', headers={'Host':'evil.example'})).status_code == 403
            assert (await c.get('/', headers={'Origin':'https://evil.example'})).status_code == 403
    asyncio.run(run())

@pytest.mark.parametrize('uri',[
    'https://evil.example/callback', 'http://chatgpt.com/connector_platform_oauth_redirect',
    'https://chatgpt.com.evil.example/connector_platform_oauth_redirect',
    'https://user@chatgpt.com/connector_platform_oauth_redirect',
    'https://chatgpt.com/connector_platform_oauth_redirect#fragment',
    'https://chatgpt.com/connector_platform_oauth_redirect?redirect=evil',
    'https://chatgpt.com/anything', 'http://localhost/callback',
])
def test_dcr_rejects_unapproved_redirects(tmp_path, uri):
    async def run():
        guard, _, _ = setup(tmp_path)
        async with client(guard) as c:
            response = await c.post('/oauth/register', json={'redirect_uris':[uri]})
            assert response.status_code == 400 and response.json()['error'] == 'invalid_redirect_uri'
    asyncio.run(run())

@pytest.mark.parametrize('method',['none','client_secret_post','client_secret_basic'])
def test_complete_login_and_authenticated_request(tmp_path, method):
    async def run():
        guard,cfg,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c, method)
            tokens = await access(c, registration)
            response = await c.post('/mcp', headers={'Authorization':'Bearer '+tokens['access_token']}, json={})
            assert response.status_code == 200 and response.json()['identity'].startswith('oauth:')
            assert (await c.post('/mcp', headers={'Authorization':'Bearer '+tokens['refresh_token']})).status_code == 401
            raw = cfg.db_path.read_bytes()
            assert PASSWORD.encode() not in raw
            assert tokens['access_token'].encode() not in raw
            assert tokens['refresh_token'].encode() not in raw
    asyncio.run(run())

def test_pkce_binding_replay_and_wrong_client(tmp_path):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            other = await register(c)
            value = await code(c, registration)
            data = exchange_data(registration,value)
            for change in ({'code_verifier':'B'*43},{'client_id':other['client_id']},{'redirect_uri':'https://evil.example'},{'resource':'https://evil.example/mcp'}):
                assert (await c.post('/oauth/token', data=data|change)).status_code == 400
            ok = await c.post('/oauth/token',data=data)
            assert ok.status_code == 200, ok.text
            assert (await c.post('/oauth/token',data=data)).status_code == 400
    asyncio.run(run())

def test_consent_cookie_csrf_password_and_replay(tmp_path):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            fields = await flow(c,registration)
            data = fields|{'password':PASSWORD,'decision':'approve'}
            assert (await c.post('/oauth/approve',data=data)).status_code == 403
            assert (await c.post('/oauth/approve',headers={'Origin':ISSUER},data=data|{'csrf':'wrong'})).status_code == 403
            assert (await c.post('/oauth/approve',headers={'Origin':ISSUER},data=data|{'password':'wrong'})).status_code == 401
            async with client(guard) as no_cookie:
                assert (await no_cookie.post('/oauth/approve',headers={'Origin':ISSUER},data=data)).status_code == 403
            ok = await c.post('/oauth/approve',headers={'Origin':ISSUER},data=data)
            assert ok.status_code == 303
            assert (await c.post('/oauth/approve',headers={'Origin':ISSUER},data=data)).status_code == 403
    asyncio.run(run())

def test_explicit_denial_returns_state_and_issuer_without_code(tmp_path):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            fields = await flow(c,registration)
            response = await c.post('/oauth/approve',headers={'Origin':ISSUER},data=fields|{'decision':'deny'})
            q = parse_qs(urlsplit(response.headers['location']).query)
            assert q['error'] == ['access_denied'] and q['iss'] == [ISSUER] and 'code' not in q
    asyncio.run(run())

def test_refresh_rotation_replay_revokes_family(tmp_path):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            first = await access(c, registration)
            original_identity = (await c.post('/mcp',headers={'Authorization':'Bearer '+first['access_token']})).json()
            data = dict(client_id=registration['client_id'],grant_type='refresh_token',refresh_token=first['refresh_token'],resource=RESOURCE)
            response = await c.post('/oauth/token',data=data)
            assert response.status_code == 200
            second = response.json()
            assert second['refresh_token'] != first['refresh_token']
            assert (await c.post('/mcp',headers={'Authorization':'Bearer '+second['access_token']})).json() == original_identity
            assert (await c.post('/oauth/token',data=data)).status_code == 400
            assert (await c.post('/mcp',headers={'Authorization':'Bearer '+second['access_token']})).status_code == 401
    asyncio.run(run())

def test_expired_token_rejected_and_revocation_supported(tmp_path):
    async def run():
        guard,_,now = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            tokens = await access(c,registration)
            now[0] += 3601
            assert (await c.post('/mcp',headers={'Authorization':'Bearer '+tokens['access_token']})).status_code == 401
            response = await c.post('/oauth/revoke',data={'client_id':registration['client_id'],'token':tokens['refresh_token']})
            assert response.status_code == 200
            response = await c.post('/oauth/token',data=dict(client_id=registration['client_id'],grant_type='refresh_token',refresh_token=tokens['refresh_token'],resource=RESOURCE))
            assert response.status_code == 400
    asyncio.run(run())

def test_client_registration_survives_lost_database(tmp_path):
    async def run():
        guard,cfg,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c,'client_secret_post')
        cfg.db_path.unlink()
        new = LocalOAuthServer(cfg)
        assert new._client(registration['client_id'])['redirect_uris'] == [REDIRECT]
        assert new._client_secret(registration['client_id']) == registration['client_secret']
    asyncio.run(run())

@pytest.mark.parametrize('changes',[
    {'code_challenge_method':'plain'}, {'code_challenge':'bad'},
    {'resource':'https://evil.example/mcp'}, {'scope':'admin'}, {'response_type':'token'},
])
def test_authorization_parameters_are_validated(tmp_path, changes):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            registration = await register(c)
            q = dict(client_id=registration['client_id'],redirect_uri=REDIRECT,response_type='code',scope=SCOPE,resource=RESOURCE,state='test',code_challenge=CHALLENGE,code_challenge_method='S256')
            assert (await c.get('/oauth/authorize',params=q|changes)).status_code == 400
    asyncio.run(run())

def test_oversized_and_duplicate_input_rejected(tmp_path):
    async def run():
        guard,_,_ = setup(tmp_path)
        async with client(guard) as c:
            response = await c.post('/oauth/register',content='x'*20000,headers={'Content-Type':'application/json'})
            assert response.status_code == 413
            response = await c.post('/oauth/register',content='{"redirect_uris": [], "redirect_uris": []}',headers={'Content-Type':'application/json'})
            assert response.status_code == 400
    asyncio.run(run())

def test_password_format_and_environment_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('UIJEONG_RESOURCE_URL',RESOURCE)
    monkeypatch.setenv('UIJEONG_BEARER_TOKEN','SYNTHETIC-SIGNING-SEED-LONGER-THAN-32')
    monkeypatch.setenv('UIJEONG_OAUTH_ADMIN_PASSWORD_HASH','')
    with pytest.raises(R.SecurityError):
        LocalOAuthConfig.from_env()
    monkeypatch.setenv('UIJEONG_OAUTH_ADMIN_PASSWORD_HASH',PASSWORD_HASH)
    monkeypatch.setenv('UIJEONG_STATE_DB',str(tmp_path/'state.sqlite3'))
    monkeypatch.setenv('UIJEONG_AUTH_MODE','oauth_local')
    monkeypatch.setenv('UIJEONG_BIND_HOST','0.0.0.0')
    monkeypatch.setenv('UIJEONG_ALLOWED_HOSTS','uijeong.example')
    policy = R.http_policy()
    assert policy['token'] == '' and policy['auth_mode'] == 'oauth_local'
    assert ISSUER in policy['origins']
