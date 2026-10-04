"""Pagination bounds match schema; expected rejection never calls upstream."""
import asyncio
import pytest
from mcp.server.fastmcp import FastMCP
import integrated_ordinance as O
import uijeong_mcp as U
from jachi.models import DocumentRef

class Registry:
    def __init__(self): self.tools={}
    def tool(self,**kwargs):
        def register(fn): self.tools[kwargs['name']]=fn; return fn
        return register

def test_public_schema_exposes_exact_bounds():
    server=FastMCP('contracts');O.register(server)
    props={t.name:t.inputSchema for t in asyncio.run(server.list_tools())}['ordinance_get_document']['properties']
    assert (props['max_chars']['minimum'],props['max_chars']['maximum'])==(200,5000)
    assert (props['limit']['minimum'],props['limit']['maximum'])==(1,30)
    props={t.name:t.inputSchema for t in asyncio.run(U.mcp.list_tools())}['council_read_source']['properties']
    assert (props['max_turns']['minimum'],props['max_turns']['maximum'])==(1,80)
    assert (props['max_chars']['minimum'],props['max_chars']['maximum'])==(100,24000)

@pytest.mark.parametrize('field,value,lo,hi',[('max_turns',140,1,80),('max_turns',0,1,80),('max_chars',24001,100,24000),('start_turn',-1,0,None),('start_char',-1,0,None)])
def test_council_expected_rejection(monkeypatch,field,value,lo,hi):
    async def forbidden(*a,**kw): raise AssertionError('upstream must not run')
    monkeypatch.setattr(U,'minutes_detail',forbidden)
    result=asyncio.run(U.council_read_source('CLIKC2479358086714915',**{field:value}))
    assert result['status']=='INVALID_INPUT'
    assert result['validation']=={'field':field,'value':value,'allowed':{'minimum':lo,'maximum':hi}}

@pytest.mark.parametrize('field,value,lo,hi',[('max_chars',8000,200,5000),('max_chars',199,200,5000),('limit',31,1,30),('offset',-1,0,None),('start_char',-1,0,None)])
def test_ordinance_expected_rejection(monkeypatch,field,value,lo,hi):
    class ForbiddenClient:
        def __init__(self,*a,**kw): raise AssertionError('client must not open')
    monkeypatch.setattr(O,'LawClient',ForbiddenClient)
    server=Registry();O.register(server)
    result=asyncio.run(server.tools['ordinance_get_document'](DocumentRef(document_id='2209592'),**{field:value}))
    assert result['code']=='invalid_input'
    assert result['validation']=={'field':field,'value':value,'allowed':{'minimum':lo,'maximum':hi}}
