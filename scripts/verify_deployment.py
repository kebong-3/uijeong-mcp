#!/usr/bin/env python3
"""Read-only remote MCP attestation. Token comes ONLY from environment, never CLI.
Health, initialize, tools/list, council_status(live=False) by default. Does not
implement login; obtain tokens via your approved auth flow. Refuses redirects.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import release_info as V
import runtime_security as R

class CheckError(Exception):pass

def decode_message(raw:bytes,content_type:str):
    try:
        text=raw.decode('utf-8')
        if 'text/event-stream' not in content_type:return json.loads(text)
        for block in text.replace('\r\n','\n').split('\n\n'):
            data='\n'.join(line[5:].lstrip() for line in block.splitlines() if line.startswith('data:'))
            if data:
                parsed=json.loads(data)
                if isinstance(parsed,dict) and ('result' in parsed or 'error' in parsed):return parsed
    except (ValueError,UnicodeError):pass
    raise CheckError('응답 형식이 JSON/완결된 SSE 메시지가 아닙니다.')

async def verify(url,token,*,live=False,transport=None):
    parts=urlsplit(url)
    if parts.path!='/mcp' or parts.query or parts.fragment or any(x in url for x in ('"','\\',' ')):
        raise CheckError('쿼리 없는 실제 HTTPS /mcp 주소를 지정하세요.')
    R.validate_url(url,[parts.hostname] if parts.hostname else [])
    if transport is None:await R._public_dns(parts.hostname)
    report={'expected_version':V.VERSION,'remote_url':url,'writes_performed':False,
            'live_source_check_requested':live,'health':None,'checks':{},'warnings':[]}
    headers={'Accept':'application/json, text/event-stream','Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    async with httpx.AsyncClient(transport=transport,follow_redirects=False,trust_env=False,
                     verify=True,timeout=httpx.Timeout(35.0)) as client:
        async def request(method,target,body=None,anonymous=False):
            h={'Accept':'application/json'} if anonymous else headers
            async with client.stream(method,target,headers=h,json=body) as resp:
                if resp.status_code in (401,403):
                    report['status']='AUTHENTICATION_OR_AUTHORIZATION_FAILED'
                    report['http_status']=resp.status_code
                    report['next_action']='MCP 인증을 먼저 확인하세요. CLIK 키 변경이나 인증 제거로 대체하지 않습니다.'
                    return None
                if resp.status_code>=300:raise CheckError(f'HTTP {resp.status_code}; 리다이렉트는 따라가지 않았습니다.')
                raw=bytearray()
                async for part in resp.aiter_bytes():
                    raw.extend(part)
                    if len(raw)>1024*1024:raise CheckError('응답이 1MiB 한도를 초과했습니다.')
                if resp.headers.get('mcp-session-id'):headers['Mcp-Session-Id']=resp.headers['mcp-session-id']
                return decode_message(bytes(raw),resp.headers.get('content-type','')) if raw else {}
        origin=f'{parts.scheme}://{parts.netloc}'
        try:report['health']=await request('GET',origin+'/healthz',anonymous=True)
        except CheckError as exc:report['warnings'].append('healthz 확인 실패: '+str(exc))
        report.pop('status',None);report.pop('http_status',None);report.pop('next_action',None)
        seq=0
        async def rpc(method,params):
            nonlocal seq
            seq+=1
            value=await request('POST',url,{'jsonrpc':'2.0','id':seq,'method':method,'params':params})
            if value is None:return None
            if not isinstance(value,dict) or value.get('id')!=seq:raise CheckError('JSON-RPC 응답 ID 불일치')
            if value.get('error'):raise CheckError('JSON-RPC 오류; 원격 오류본문은 출력하지 않습니다.')
            return value.get('result')
        initialized=await rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},
                              'clientInfo':{'name':'uijeong-release-verifier','version':V.VERSION}})
        if initialized is None:return report
        if not isinstance(initialized,dict) or not initialized.get('protocolVersion'):raise CheckError('초기화 응답 오류')
        headers['MCP-Protocol-Version']=initialized['protocolVersion']
        notification=await request('POST',url,{'jsonrpc':'2.0','method':'notifications/initialized'})
        if notification is None:return report
        tools=[];cursor=None;seen=set()
        for _ in range(10):
            result=await rpc('tools/list',{'cursor':cursor} if cursor else {})
            if result is None:return report
            if not isinstance(result,dict) or not isinstance(result.get('tools'),list):raise CheckError('tools/list 형식 오류')
            tools.extend(result['tools']);cursor=result.get('nextCursor')
            if not cursor:break
            if cursor in seen:raise CheckError('반복 tools/list cursor')
            seen.add(cursor)
        else:raise CheckError('tools/list 페이지 상한 초과')
        called=await rpc('tools/call',{'name':'council_status','arguments':{'live':bool(live)}})
        if called is None:return report
        if not isinstance(called,dict) or called.get('isError'):raise CheckError('council_status 도구 오류')
        status=called.get('structuredContent')
        if not isinstance(status,dict):raise CheckError('council_status 구조화 응답 없음; 구형 연결 여부를 확인하세요.')
        contracts=json.loads((ROOT/'docs/source-tool-contracts.json').read_text())
        profile=status.get('profile');expected=set(contracts['profiles'].get(profile,[]))
        names={t.get('name') for t in tools};defs={t['name']:t for t in contracts['tools']}
        differences=[]
        for tool in tools:
            name=tool.get('name');actual=tool.get('inputSchema',{});source=defs.get(name)
            if source and (set(actual.get('properties',{}))!=set(source['parameters']) or
                           set(actual.get('required',[]))!=set(source['required'])):differences.append(name)
        report['observed']={'version':status.get('version'),'profile':profile,'tool_count':len(tools),
                            'deployment_commit':status.get('deployment_commit'),'live_checks':status.get('live_checks',[])}
        report['checks']={'version_matches':status.get('version')==V.VERSION,
          'runtime_fingerprint_matches':status.get('runtime_fingerprint')==V.runtime_fingerprint(ROOT),
          'remote_manifest_matches':status.get('release_verification',{}).get('status')=='MATCH',
          'tool_names_match_profile':bool(expected) and names==expected,
          'tool_parameter_names_and_required_match':not differences,
          'known_profile':profile in contracts['profiles']}
        report['tool_parameter_differences']=differences
        report['status']='MATCH' if all(report['checks'].values()) else 'MISMATCH'
        report['limitations']=['코드·등록 도구 대조이며 ChatGPT 로그인 E2E 시험은 아닙니다.',
            '매개변수명·필수항목을 대조하며 SDK JSON Schema 전체 동등성 판정은 아닙니다.',
            'healthz 200만으로 인증·CLIK·홈페이지 연결 성공을 판정하지 않습니다.']
        return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True)
    p.add_argument('--live',action='store_true',help='CLIK/홈페이지 실제 읽기 점검 추가')
    args=p.parse_args()
    token=os.environ.get('UIJEONG_VERIFY_TOKEN') or os.environ.get('UIJEONG_BEARER_TOKEN','')
    try:result=asyncio.run(verify(args.url,token,live=args.live))
    except (CheckError,R.SecurityError,httpx.HTTPError,OSError,ValueError) as exc:
        # Never include request headers, response body, token, or exception repr.
        result={'status':'CHECK_FAILED','reason_type':type(exc).__name__,
                'message':R.redact_secrets(str(exc)) if isinstance(exc,(CheckError,R.SecurityError)) else '네트워크·설정 확인 실패'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result.get('status')=='MATCH' else 1
if __name__=='__main__':sys.exit(main())
