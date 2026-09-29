"""Official MCP SDK transport; public HTTP and local stdio have separate tool sets."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from .extended import IntegratedService,VERSION,INSTRUCTIONS
from .extra_tools import available_tools
from .tools import validate_schema
from .money import BudgetError
from .api import redact

MAX_OUTPUT=300000
MAX_REQUEST=512*1024


def runtime_fingerprint():
    files=sorted(Path(__file__).parent.glob('*.py'))+[Path(__file__).with_name('api_catalog.json')]
    text=''.join(p.name+':'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n' for p in files)
    return hashlib.sha256(text.encode()).hexdigest()


def build_mcp(service):
    import anyio
    import mcp.types as types
    from mcp.server.lowlevel import Server
    server=Server('local-budget-mcp',version=VERSION,instructions=INSTRUCTIONS)
    registry={t['name']:t for t in available_tools(service.public)}

    @server.list_tools()
    async def list_tools():
        return [types.Tool(**{k:v for k,v in t.items() if k not in ('method','public')}) for t in registry.values()]

    @server.call_tool(validate_input=False)
    async def call_tool(name,arguments):
        error=False
        try:
            if name not in registry:raise BudgetError('현재 프로필에서 사용할 수 없는 도구입니다.')
            args={} if arguments is None else arguments
            validate_schema(args,registry[name]['inputSchema'])
            result=await anyio.to_thread.run_sync(lambda:getattr(service,registry[name]['method'])(**args))
            result=redact(result)
            text=json.dumps(result,ensure_ascii=False,allow_nan=False)
            if len(text.encode())>MAX_OUTPUT:raise BudgetError('출력 한도 초과: 페이지/대상 수를 줄이세요. 로컬 결과는 budget_export로 확인하세요.')
            error=result.get('status')=='ERROR'
        except BudgetError as exc:
            error=True;result={'status':'INVALID_INPUT_OR_PROCESSING_ERROR','message':redact(str(exc)),
                               'note':'오류를 자료 없음이나 0원으로 바꾸지 마세요.'}
            text=json.dumps(result,ensure_ascii=False)
        except Exception:
            error=True;result={'status':'ERROR','message':'처리 오류. 인증정보·입력자료는 로그에 남기지 않았습니다.'}
            text=json.dumps(result,ensure_ascii=False)
        return types.CallToolResult(content=[types.TextContent(type='text',text=text)],structuredContent=result,isError=error)

    return server


class HTTPGuard:
    """Host/Origin and optional token checks; public HTTP never has local tools."""
    def __init__(self,app,hosts,origins,token=''):
        self.app=app;self.hosts=set(hosts);self.origins=set(origins);self.token=token
        self.recent=deque();self.active=0

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        from starlette.responses import JSONResponse
        async def fail(code,message):
            return await JSONResponse({'error':message},status_code=code,headers={'Cache-Control':'no-store'})(scope,receive,send)
        raw=scope.get('headers',[])
        if sum(k.lower()==b'origin' for k,v in raw)>1:return await fail(400,'Invalid Origin')
        if sum(k.lower()==b'host' for k,v in raw)!=1:return await fail(400,'Invalid Host')
        headers={k.lower():v.decode('latin1') for k,v in raw}
        try:host=urlsplit('//'+headers.get(b'host','')).hostname
        except ValueError:return await fail(400,'Invalid Host')
        if host not in self.hosts:return await fail(403,'Host not allowed')
        origin=headers.get(b'origin')
        if origin and origin not in self.origins:return await fail(403,'Origin not allowed')
        if scope.get('path')=='/mcp':
            if self.token and not secrets.compare_digest(headers.get(b'authorization',''),'Bearer '+self.token):
                return await fail(401,'Authentication required')
            if scope['method']!='POST':return await fail(405,'Use MCP Streamable HTTP POST; GET stream not offered')
            now=time.monotonic()
            while self.recent and now-self.recent[0]>=60:self.recent.popleft()
            if len(self.recent)>=240:return await fail(429,'Instance request rate limit')
            if self.active>=12:return await fail(503,'Instance concurrency limit')
            self.recent.append(now)
        self.active+=1
        async def safe_send(message):
            if message['type']=='http.response.start':
                extra=[(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff')]
                message={**message,'headers':list(message.get('headers',[]))+extra}
            await send(message)
        try:return await self.app(scope,receive,safe_send)
        finally:self.active-=1


def build_app(service=None,hosts=None,origins=None,token=None):
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse,HTMLResponse
    from html import escape
    service=service or IntegratedService(public=True)
    if not service.public:raise BudgetError('내부 파일 도구는 HTTP로 제공하지 않습니다. 로컬 stdio를 사용하세요.')
    hosts=hosts or [h.strip() for h in os.getenv('BUDGET_ALLOWED_HOSTS','localhost,127.0.0.1,local-budget-mcp.onrender.com').split(',') if h.strip()]
    rendered=os.getenv('RENDER_EXTERNAL_HOSTNAME','')
    if rendered and rendered not in hosts:hosts.append(rendered)
    origins=origins if origins is not None else [x.strip() for x in os.getenv('BUDGET_ALLOWED_ORIGINS','https://chatgpt.com').split(',') if x.strip()]
    if '*' in hosts or '*' in origins:raise BudgetError('전체 Host/Origin 허용은 지원하지 않습니다.')
    token=os.getenv('BUDGET_HTTP_TOKEN','') if token is None else token
    if token and (len(token)<32 or not token.isascii()):raise BudgetError('선택적 HTTP 토큰은 32자 이상 ASCII 임의값이어야 합니다.')
    sdk_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
        allowed_hosts=[v for h in hosts for v in (h,h+':*')],allowed_origins=origins)
    server=build_mcp(service)
    manager=StreamableHTTPSessionManager(app=server,json_response=True,stateless=True,
        security_settings=sdk_security,max_request_body_size=MAX_REQUEST)
    fingerprint=runtime_fingerprint()

    class MCPRoute:
        async def __call__(self,scope,receive,send):
            return await manager.handle_request(scope,receive,send)

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():yield

    async def health(request):
        return JSONResponse({'status':'process_ready','service':'local-budget-mcp','version':VERSION,'profile':'public',
            'mcp_endpoint':'/mcp','tool_count':len(available_tools(True)),'private_tools_exposed':False,
            'runtime_fingerprint':fingerprint,'build_commit':os.getenv('RENDER_GIT_COMMIT','not_on_render'),
            'external_api_validation':'Call budget_api_status; process health is not API verification'})

    async def setup(request):
        return JSONResponse({'service':'local-budget-mcp','version':VERSION,
            'configuration':service.api_status(),'api_catalog':service.api_catalog()['items'],
            'instructions':'Render Environment에서 필요한 키의 Value만 입력 후 Save, rebuild, and deploy. 키를 채팅이나 GitHub에 넣지 마세요.'})

    async def index(request):
        rows=''.join('<tr><td>'+escape(x['name'])+'</td><td>'+escape(x['credential_env'])+'</td><td><a rel="noreferrer" href="'+escape(x['application_url'],quote=True)+'">공식 신청 안내</a></td></tr>' for x in service.api_catalog()['items'])
        return HTMLResponse('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>지방예산 MCP</title>'
          '<style>body{font-family:system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:24px;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}code{background:#eee;padding:3px}a{color:#165d91}</style>'
          '<h1>지방예산 MCP '+VERSION+'</h1><p>공식 재정자료 조회 · 예산산출 · 재원분담 · 다년도 비용 · 네 역할 교차검산</p>'
          '<p>MCP 연결 주소: <code>/mcp</code> | <a href="/healthz">서버 상태</a> | <a href="/setup">API 설정 상태</a></p>'
          '<p><strong>공개 서버에는 비공개 예산요구안·개인정보·인증키를 입력하지 마세요.</strong> 내부 파일·SQLite 기능은 로컬 stdio 전용입니다.</p>'
          '<p><a href="/staff">직원 설치·사용 안내</a> · 직원별 API 신청 없이 연결하는 방법과 업무 질문 예시를 확인하세요.</p>'
          '<p>키 입력 전에도 산술 도구는 작동합니다. 공식 API는 키 설정과 실제 응답 검증을 구분합니다.</p>'
          '<table><tr><th>API 기능</th><th>Render Key</th><th>발급처</th></tr>'+rows+'</table></html>',
          headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})

    from .staff_portal import staff_routes
    app=Starlette(routes=[Route('/',index),Route('/healthz',health),Route('/health',health),Route('/setup',setup),
                         Route('/mcp',MCPRoute(),methods=['POST','GET','DELETE'])]+staff_routes(),lifespan=lifespan)
    return HTTPGuard(app,hosts,origins,token)


def start():
    p=argparse.ArgumentParser(description='local-budget-mcp: official SDK public HTTP / local files stdio')
    p.add_argument('--http',action='store_true')
    p.add_argument('--workspace',default=os.getenv('BUDGET_HOME','./budget-workspace'))
    p.add_argument('--public',action='store_true',help='stdio에서도 공개 도구만 제공')
    args=p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if args.http:
        import uvicorn
        uvicorn.run(build_app(),host='0.0.0.0',port=int(os.getenv('PORT','8000')),access_log=False,
                    proxy_headers=False,timeout_keep_alive=10,limit_concurrency=20,log_level='warning')
    else:
        import mcp.server.stdio
        service=IntegratedService(args.workspace,public=args.public)
        server=build_mcp(service)
        async def run():
            async with mcp.server.stdio.stdio_server() as (read,write):
                await server.run(read,write,server.create_initialization_options())
        asyncio.run(run())

