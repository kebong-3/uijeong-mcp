import asyncio
import pytest
import finance_context as F
import v3_reliability as V


def test_live_observed_catalog_field_names():
    payload={'result':{'data':[{'dataName':'가상기관_직원복지 공개자료','detailPageUrl':'https://www.data.go.kr/data/15112888/openapi.do','organization':'가상기관','dataType':'API','updateDate':'2026-09-28'}],'sum':1,'dataCount':1}}
    result=V.parse_discovery(payload,3)
    assert result['status']=='COMPLETE'
    assert result['items'][0]['title']=='가상기관_직원복지 공개자료'
    assert result['items'][0]['provider']=='가상기관'
    assert result['items'][0]['detail_url'].startswith('https://www.data.go.kr/')
    assert result['items'][0]['actual_values_fetched'] is False


def test_finance_probe_uses_required_date_without_claiming_data(monkeypatch):
    monkeypatch.setenv('LOFIN_API_KEY','synthetic')
    async def request(params):
        assert params['exe_ymd']==V.today().strftime('%Y%m%d')
        assert params['pSize']==1
        return {'result_code':'INFO-200','rows':[],'total_count':0}
    monkeypatch.setattr(F,'_request',request)
    result=asyncio.run(V.finance_ping())
    assert result['status']=='PARTIAL'
    assert result['data_returned'] is False
