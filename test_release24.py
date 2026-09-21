"""Deployment validator with synthetic HTTP; no remote deployment claim."""
import asyncio
import json
from pathlib import Path
import sys
import httpx
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from source_contracts import build
from verify_deployment import verify, CheckError, decode_message
import release_info as V

def test_source_profiles_still_match_supported_tool_counts():
    c=build();assert {k:len(v) for k,v in c['profiles'].items()}=={'core':5,'work':18,'lite':26,'full':38}
    defs={t['name']:t for t in c['tools']}
    assert 'department_aliases' in defs['council_department_brief']['parameters']
    assert 'period_mode' in defs['council_recurring_issues']['parameters']
    assert 'live' in defs['council_status']['parameters']
    assert c['generation_method']=='AST_SOURCE_NOT_RUNTIME_SDK'

def mock_transport(*,reject=False,redirect=False,stale=False):
    c=build();defs={t['name']:t for t in c['tools']};calls=[]
    def handle(req):
        calls.append(req)
        if req.url.path=='/healthz':return httpx.Response(200,json={'status':'ok','version':V.VERSION})
        if reject:return httpx.Response(401,json={'error':'auth'})
        if redirect:return httpx.Response(302,headers={'Location':'https://untrusted.example/mcp'})
        body=json.loads(req.content);method=body['method']
        if method=='notifications/initialized':return httpx.Response(202)
        if method=='initialize':result={'protocolVersion':'2025-11-25'}
        elif method=='tools/list':
            result={'tools':[{'name':name,'inputSchema':{'properties':dict.fromkeys(defs[name]['parameters'],{}),
                      'required':defs[name]['required']}} for name in c['profiles']['work']]}
            if stale:result['tools'][0]['inputSchema']['properties']={}
        else:
            result={'structuredContent':{'version':V.VERSION,'profile':'work','runtime_fingerprint':V.runtime_fingerprint(ROOT),
                         'release_verification':{'status':'MATCH'},'live_checks':[]}}
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':result})
    return httpx.MockTransport(handle),calls

def test_validator_compares_hashes_and_properties_not_just_version():
    t,calls=mock_transport(stale=True)
    r=asyncio.run(verify('https://example.com/mcp','SYNTHETIC_TOKEN',transport=t))
    assert r['status']=='MISMATCH' and not r['checks']['tool_parameter_names_and_required_match']
    assert r['checks']['version_matches']

def test_validator_success_is_only_synthetic_attestation():
    t,calls=mock_transport()
    r=asyncio.run(verify('https://example.com/mcp','SYNTHETIC_TOKEN',transport=t))
    assert r['status']=='MATCH'
    assert 'authorization' not in calls[0].headers
    assert 'SYNTHETIC_TOKEN' not in json.dumps(r)

def test_healthy_server_does_not_hide_failed_auth():
    t,calls=mock_transport(reject=True)
    r=asyncio.run(verify('https://example.com/mcp','bad',transport=t))
    assert r['health']['status']=='ok' and r['status']=='AUTHENTICATION_OR_AUTHORIZATION_FAILED'

def test_validator_never_follows_redirect_with_token():
    t,calls=mock_transport(redirect=True)
    with pytest.raises(CheckError):asyncio.run(verify('https://example.com/mcp','SYNTHETIC',transport=t))
    assert len(calls)==2 and {r.url.host for r in calls}=={'example.com'}

@pytest.mark.parametrize('url',['http://example.com/mcp','https://127.0.0.1/mcp','https://example.com/mcp?token=x',
    'https://user:secret@example.com/mcp','https://example.com/mcp#part'])
def test_unsafe_validator_url_is_not_contacted(url):
    t,calls=mock_transport()
    with pytest.raises((CheckError,ValueError)):asyncio.run(verify(url,'secret',transport=t))
    assert not calls

def test_json_and_sse_decoding():
    r={'jsonrpc':'2.0','id':1,'result':{}}
    assert decode_message(('data: '+json.dumps(r)+'\n\n').encode(),'text/event-stream')==r

def test_manifest_mismatch_detected(tmp_path):
    (tmp_path/'one.py').write_text('x=1')
    hashes=V.module_hashes(tmp_path)
    (tmp_path/'release_manifest.json').write_text(json.dumps({'version':V.VERSION,'runtime_sha256':hashes}))
    assert V.verify_manifest(tmp_path)['status']=='MATCH'
    (tmp_path/'one.py').write_text('x=2')
    assert V.verify_manifest(tmp_path)['status']=='MISMATCH'
