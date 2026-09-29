"""Anonymous deployed MCP verification. No credentials or returned evidence printed."""
from __future__ import annotations
import argparse
import asyncio
import json
import time
from urllib.parse import urlsplit
import httpx


def payload(result):
    if isinstance(result.get('structuredContent'), dict):
        return result['structuredContent']
    for block in result.get('content', []):
        if block.get('type') == 'text':
            try:
                value = json.loads(block['text'])
                if isinstance(value, dict): return value
            except (ValueError, KeyError): pass
    return {}


async def verify(url: str, calls=None):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Use an HTTPS MCP URL without credentials')
    report = {'url':url, 'authentication':'none', 'checks':{}, 'calls':[]}
    headers = {'accept':'application/json, text/event-stream', 'mcp-protocol-version':'2025-11-25'}
    async with httpx.AsyncClient(headers=headers, timeout=75, follow_redirects=False) as client:
        async def rpc(method, params, request_id):
            response = await client.post(url, json={'jsonrpc':'2.0','id':request_id,'method':method,'params':params})
            response.raise_for_status()
            body = response.json()
            if body.get('error'): raise RuntimeError('MCP protocol error: '+str(body['error'].get('code')))
            return body['result']
        init = await rpc('initialize', {'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'unified-release-check','version':'1'}},1)
        report['checks']['initialize'] = bool(init.get('protocolVersion'))
        listing = await rpc('tools/list',{},2)
        names = {tool['name'] for tool in listing['tools']}
        report['tool_count'] = len(names)
        for domain in ('council','budget','ordinance'):
            report['checks'][domain+'_tools'] = any(name.startswith(domain+'_') for name in names)
        for i, call in enumerate(calls or [{'name':'council_status','arguments':{'live':False}}],3):
            started=time.monotonic()
            result=await rpc('tools/call',call,i)
            data=payload(result)
            report['calls'].append({'tool':call['name'], 'seconds':round(time.monotonic()-started,2),
                'isError':bool(result.get('isError')), 'status':data.get('status'),
                'code':data.get('code'), 'response_bytes':len(json.dumps(result).encode())})
        report['checks']['calls_returned'] = all(not call['isError'] and call['status'] not in ('ERROR','NOT_CONFIGURED','TIMEOUT','OUTPUT_LIMIT','INVALID_INPUT','INVALID_INPUT_OR_PROCESSING_ERROR','unavailable') for call in report['calls'])
    report['status']='PASS' if all(report['checks'].values()) else 'FAIL'
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--calls-json', help='JSON file containing [{name,arguments}] for live source checks')
    args=parser.parse_args()
    calls=json.load(open(args.calls_json,encoding='utf-8')) if args.calls_json else None
    try: report=asyncio.run(verify(args.url,calls))
    except Exception as exc: report={'status':'FAIL','error_type':type(exc).__name__}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['status']=='PASS' else 1)

if __name__=='__main__':main()
