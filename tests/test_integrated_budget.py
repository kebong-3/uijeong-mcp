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


def test_procurement_unknown_envelope_diagnostic_is_safe(monkeypatch):
    from budget_mcp.api import Gateway
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', 'PRIVATE_TEST_KEY_1234')
    payload = {'error': {'code': '20', 'message': 'PRIVATE_TEST_KEY_1234',
                          'PRIVATE_TEST_KEY_1234': 'echo'}, 'PRIVATE_TEST_KEY_1234': 'echo'}
    gateway = Gateway(fetch=lambda url,params:json.dumps(payload).encode())
    result = gateway.fetch_api('contracts_servc', {'inqryDiv':'1'})
    assert result['status'] == 'ERROR'
    assert result['coverage'] == 'REQUEST_FAILED'
    assert result['provider_diagnostic']['provider_codes'] == [{'path':'$.error.code', 'code':'20'}]
    assert 'PRIVATE_TEST_KEY_1234' not in json.dumps(result)


def test_procurement_diagnostics_do_not_accept_alternate_success():
    import pytest
    from budget_mcp.api import parse_procurement, ProcurementResponseError
    for payload in ({'header': {'rsltCd':'00'}}, {'response': []}, {'response':{'header':[]}}, []):
        with pytest.raises(ProcurementResponseError):
            parse_procurement(payload)
    assert parse_procurement({'response': {'header': {'resultCode': '00'},
                              'body': {'totalCount':0, 'items':[]}}}) == ([],0)


def test_procurement_unknown_class_envelope_and_secret_property(monkeypatch):
    from budget_mcp.api import procurement_diagnostic
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', 'AlphabeticSecret')
    result = procurement_diagnostic({'Provider.ResponseError':{'header':{'resultCode':'20', 'resultMsg':'never echo'}},
                                     'AlphabeticSecret':{'code':'30'}})
    assert result['provider_codes'] == [{'path':'$.Provider.ResponseError.header.resultCode','code':'20'}]
    assert result['envelopes'][0]['other_key_names'] == ['Provider.ResponseError']
    assert 'AlphabeticSecret' not in json.dumps(result)
    assert 'never echo' not in json.dumps(result)


def test_procurement_error_wrapper_exposes_verified_code_not_values():
    import pytest
    from budget_mcp.api import parse_procurement, ProcurementResponseError
    with pytest.raises(ProcurementResponseError, match='06.*YYYYMMDD') as caught:
        parse_procurement({'nkoneps.com.response.ResponseError': {'header': {'resultCode':'06', 'resultMsg':'private echo'}}})
    assert 'private echo' not in str(caught.value)


def test_contract_dates_use_eight_digits_and_fail_before_network(monkeypatch):
    import pytest
    from budget_mcp.api import Gateway
    from budget_mcp.money import BudgetError
    monkeypatch.setenv('DATA_GO_KR_SERVICE_KEY', 'PRIVATE_TEST_KEY_1234')
    calls=[]
    def fetch(url,params):
        calls.append(params)
        return json.dumps({'response':{'header':{'resultCode':'00'},'body':{'totalCount':0,'items':[]}}}).encode()
    gateway=Gateway(fetch=fetch)
    for begin,end in [('202609010000','202609012359'),('20260230','20260301'),('20260902','20260901')]:
        with pytest.raises(BudgetError):
            gateway.fetch_api('contracts_servc',{'inqryDiv':'1','inqryBgnDate':begin,'inqryEndDate':end})
    assert calls==[]
    result=gateway.fetch_api('contracts_servc',{'inqryDiv':'1','inqryBgnDate':'20260901','inqryEndDate':'20260901'})
    assert result['status']=='EMPTY'
    assert calls[0]['inqryBgnDate']=='20260901'
    spec=gateway.api_catalog('contracts_servc')['items'][0]
    assert 'YYYYMMDD' in spec['parameter_formats']['inqryBgnDate']
