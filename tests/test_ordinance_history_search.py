import pytest
import integrated_ordinance as mod
from jachi.normalize import listing_rows
from test_integrated_ordinance import Registry


def test_promulgation_number_preserved_across_separate_effective_versions():
    rows=listing_rows({'OrdinSearch':{'ordin':[
        {'자치법규명':'시험조례','자치법규ID':'1','자치법규일련번호':'10','공포일자':'20260616','공포번호':'제123호'},
        {'자치법규명':'시험조례','자치법규ID':'1','자치법규일련번호':'11','공포일자':'20260616','공포번호':'제123호'}
    ]}},'ordinance')
    assert len(rows)==2
    assert [r['promulgation_number'] for r in rows]==['제123호','제123호']


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def history_search(monkeypatch):
    captured=[]
    class Client:
        def __init__(self,*a,**kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*a): pass
        async def search(self,query,**kwargs):
            captured.append((query,kwargs))
            return {'results':[{'document_id':'1','mst':str(i)} for i in range(12)],
                    'coverage':{'next_page':2,'query_fully_scanned':False},'status':'partial'}
    monkeypatch.setattr(mod,'LawClient',Client)
    registry=Registry(); mod.register(registry)
    return registry.tools['ordinance_search'],captured


@pytest.mark.anyio
async def test_history_translates_official_dates_and_retains_versions(history_search):
    search,captured=history_search
    result=await search('*',jurisdiction='광주광역시 서구',history=True,
        promulgation_from='2024-01-01',promulgation_to='2026-10-16',org='6290000',sborg='3600000',limit=5,offset=5)
    args=captured[0][1]
    assert args['history'] is True
    assert args['extra']=={'ancYd':'20240101~20261016','sort':'ddes'}
    assert args['org']=='6290000' and args['sborg']=='3600000'
    assert result['history_scope']=='historical_versions'
    assert result['promulgation_filter']=={'from':'2024-01-01','to':'2026-10-16','applied':True}
    assert [r['mst'] for r in result['results']]==['5','6','7','8','9']
    assert result['next_offset']==10 and result['coverage']['next_page']==2


@pytest.mark.anyio
async def test_existing_default_is_current_and_has_no_date_filter(history_search):
    search,captured=history_search
    result=await search('지원')
    assert captured[0][1]['history'] is False
    assert captured[0][1]['extra']=={}
    assert result['history_scope']=='current_versions'
    assert result['promulgation_filter']['applied'] is False


@pytest.mark.anyio
@pytest.mark.parametrize('bad',[
    {'promulgation_from':'2024-01-01'},
    {'promulgation_from':'2026-10-16','promulgation_to':'2024-01-01'},
    {'promulgation_from':'2025-02-30','promulgation_to':'2026-01-01'},
    {'promulgation_from':'20240101','promulgation_to':'20260101'},
    {'kind':'law','history':True},
    {'kind':'law','org':'6290000'},
    {'sborg':'3600000'},
    {'org':'6290000&OC=x'},
])
async def test_invalid_filters_rejected_before_official_call(history_search,bad):
    search,captured=history_search
    result=await search('지원',**bad)
    assert result['status']=='unavailable' and result['code']=='invalid_input'
    assert not captured
