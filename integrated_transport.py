"""Compact MCP boundary for stateless budget, ordinance and workflow tools."""
from __future__ import annotations
import asyncio
import functools
import inspect
import json
import time
import uuid
import anyio
from mcp.types import CallToolResult, TextContent
import runtime_security as R
import release_info

MAX_RESULT_CHARS = 30000
TIMEOUT_SECONDS = 30
ERROR_STATES = frozenset({'ERROR', 'INVALID_INPUT', 'INVALID_INPUT_OR_PROCESSING_ERROR',
    'TIMEOUT', 'NOT_CONFIGURED', 'OUTPUT_LIMIT', 'UNAVAILABLE', 'FAILED', 'BLOCKED'})

def scrub(value):
    if isinstance(value, str): return R.redact_secrets(value)
    if isinstance(value, dict): return {R.redact_secrets(k): scrub(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [scrub(v) for v in value]
    return value

def wrap(fn):
    annotations = inspect.get_annotations(fn, eval_str=True)
    signature = inspect.signature(fn).replace(parameters=[
        p.replace(annotation=annotations.get(p.name,p.annotation)) for p in inspect.signature(fn).parameters.values()],
        return_annotation=CallToolResult)
    @functools.wraps(fn)
    async def run(*args, **kwargs):
        started=time.monotonic()
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                if inspect.iscoroutinefunction(fn): result=await fn(*args,**kwargs)
                else: result=await anyio.to_thread.run_sync(functools.partial(fn,*args,**kwargs),abandon_on_cancel=True)
            if not isinstance(result,dict): result={'result':result}
            result=scrub(result)
            raw=json.dumps(result,ensure_ascii=False,allow_nan=False,default=str)
            if len(raw)>MAX_RESULT_CHARS:
                result={'status':'OUTPUT_LIMIT','original_chars':len(raw),
                    'message':'결과가 응답 한도를 넘었습니다. 페이지 크기·비교 문서·조문 수를 줄여 다시 조회하세요.',
                    'tool':fn.__name__,'evidence_returned':False}
        except TimeoutError:
            result={'status':'TIMEOUT','message':'조회 시간 초과. 범위를 줄여 재시도하세요. 자료 없음이 아닙니다.'}
        except Exception as exc:
            result={'status':'ERROR','message':R.safe_error(exc)}
        result['mcp_receipt']={'tool':fn.__name__,'server_version':release_info.VERSION,
            'request_id':uuid.uuid4().hex[:20],'elapsed_ms':round((time.monotonic()-started)*1000),
            'meaning':'서버 실행 기록. 실제 출처 조회 여부는 결과 상태로 확인하세요.'}
        raw=json.dumps(result,ensure_ascii=False,allow_nan=False,default=str)
        state=str(result.get('status','RETURNED')).upper()
        text=raw if len(raw)<=5000 else f'{fn.__name__}: {state}. 전체 결과와 출처는 structuredContent에 있습니다.'
        return CallToolResult(content=[TextContent(type='text',text=text)],structuredContent=result,isError=state in ERROR_STATES)
    run.__signature__=signature
    run.__annotations__={**annotations,'return':CallToolResult}
    return run

class Registry:
    def __init__(self,server): self.server=server
    def tool(self,**kwargs):
        def decorate(fn):
            self.server.tool(**kwargs)(wrap(fn))
            return fn
        return decorate
