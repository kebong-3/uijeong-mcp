import asyncio
import json
from mcp.server.fastmcp import FastMCP
import integrated_budget as B


def test_public_service_never_creates_store():
    assert B.service().public
    assert B.service().store is None
    assert B.invoke('budget_import', {})['status'] == 'INVALID_INPUT'


def test_amount_units_and_unknown_preserved():
    r = B.invoke('budget_change', {'before': '100', 'after': '120', 'unit': '천원'})
    assert r['delta_won'] == 20000
    assert r['rate_pct'] == '20.00'
    r = B.invoke('budget_change', {'before': None, 'after': '120'})
    assert r.get('delta_won') is None


def test_invalid_float_and_extra_keys_rejected():
    for args in ({'before': 0.1, 'after': '10'}, {'before': '0', 'after': '10', 'file': '/etc/passwd'}):
        assert B.invoke('budget_change', args)['status'] == 'INVALID_INPUT_OR_PROCESSING_ERROR'


def test_no_key_does_not_return_empty(monkeypatch):
    monkeypatch.delenv('LOFIN_API_KEY', raising=False)
    result = B.invoke('budget_fetch_api', {'api_id': 'lofin_projects', 'params': {'fyr': '2026', 'exe_ymd': '20260929'}})
    assert result['status'] == 'NOT_CONFIGURED'


def test_mcp_registered_tool_call():
    async def run():
        mcp = FastMCP('test')
        B.register(mcp)
        names = {t.name for t in await mcp.list_tools()}
        assert names == set(B.TOOL_NAMES)
        assert not any(x in names for x in ('budget_import', 'budget_rows', 'budget_export', 'budget_delete'))
        content = await mcp.call_tool('budget_calculate', {'operation':'change','arguments':{'before':'100','after':'150'}})
        assert '50' in str(content)
    asyncio.run(run())
