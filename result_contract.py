"""Preserve structured data, bound its size, and mark known failures at the MCP boundary.

The structured result is the canonical channel. MCP also asks servers to put the
serialized JSON in a text block for clients that ignore structured output, so a
small result carries both. A large result would then be sent twice and cross the
model's context window, so past a threshold the text block carries a digest and
names structuredContent as the place to read the rest.

Thresholds come from response_budget and are environment-tunable.
"""
import functools
import json
import re
import response_budget as B
import runtime_security as R


def wire_result(fn):
    @functools.wraps(fn)
    async def wrapped(*args, **kwargs):
        from mcp.types import CallToolResult, TextContent
        result = await fn(*args, **kwargs)
        if isinstance(result, dict):
            from evidence_links import attach_source_links
            result = attach_source_links(result, fn.__name__)
            bounded = B.apply_budget(result)
            code = bounded.get('status')
            raw = json.dumps(bounded, ensure_ascii=False)
            if len(raw) <= B.text_json_max_chars():
                text = raw          # 소형 결과: 구버전 클라이언트 호환을 위해 직렬화 본문 유지
            else:
                text = B.digest(bounded)
            return CallToolResult(content=[TextContent(type='text', text=text)],
                                  structuredContent=bounded,
                                  isError=code in ('ERROR', 'INVALID_INPUT'))
        if isinstance(result, str):
            capped = B.max_chars()
            if len(result) > capped:
                original_len=len(result)
                if result.startswith('상태: COMPLETE'):
                    result=result.replace('상태: COMPLETE','상태: PARTIAL',1)
                note=f"\n\n[응답 한도 {capped:,}자. 원문 {original_len:,}자 중 일부 표시 — 구조화 도구 council_get_evidence 또는 council_read_source로 나눠 확인하세요.]"
                result=result[:max(0,capped-len(note))]+note
            if re.search(r'^상태:\s*(ERROR|INVALID_INPUT)', result):
                return CallToolResult(content=[TextContent(type='text', text=result)],
                                      structuredContent={'result': result}, isError=True)
            return result
        return result
    return wrapped
