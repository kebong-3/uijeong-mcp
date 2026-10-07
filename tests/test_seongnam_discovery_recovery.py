"""Display compaction must not become the input to internal evidence discovery."""
import asyncio
import copy
from types import SimpleNamespace
import pytest
import evidence_quality as Q
import evidence_discovery as D
import openai_compat as O
import v3_reliability as V
import council_extensions as C
import legal_context as L
import finance_context as F
import integrated_ordinance as IO


def source():
    text = '행정자료 설명입니다. ' * 65 + '소규모 공동주택을 대상으로 빌라가꿈관리소를 운영합니다.'
    event = {'source_kind':'OFFICIAL_FETCHED', 'docid':'OFFLINE1','event_id':'event1',
             'speech':{'text':text,'turn_index':3,'citation':{'source_kind':'OFFICIAL_FETCHED','docid':'OFFLINE1','turn_index':3}}}
    return {'parameters':{'keyword':'빌라가꿈관리소'},'items':[event]}


def test_full_snapshot_not_display_excerpt_is_discovery_input():
    full = source()
    slim = {'parameters':full['parameters'],'snapshot_id':'S1','items':[Q.thin_event(full['items'][0])]}
    before = copy.deepcopy(slim)
    backend = SimpleNamespace(V2_SERVICES={'snapshots':SimpleNamespace(get=lambda sid: full)})
    rows, receipt = Q.discovery_input(backend,slim)
    assert not D.discover_subjects(slim['items'],'빌라가꿈관리소')
    assert D.discover_subjects(rows,'빌라가꿈관리소')[0]['term']=='소규모 공동주택'
    assert receipt['status']=='SNAPSHOT_REUSED' and receipt['network_calls']==0
    assert receipt['public_output_expanded'] is False
    assert slim==before


@pytest.mark.parametrize('stored', [None, {'parameters':{'keyword':'different'},'items':[{'docid':'HIDDEN'}]}])
def test_unavailable_or_different_scope_snapshot_is_not_used(stored):
    backend = SimpleNamespace(V2_SERVICES={'snapshots':SimpleNamespace(get=lambda sid:stored)})
    shown=[{'docid':'VISIBLE'}]
    rows, receipt=Q.discovery_input(backend,{'items':shown,'snapshot_id':'S','parameters':{'keyword':'x'}})
    assert rows==shown and receipt['status']=='PARTIAL'
    assert 'HIDDEN' not in str(receipt)


def test_snapshot_exception_cannot_disclose_private_message():
    def fail(sid):raise RuntimeError('PRIVATE_CREDENTIAL_SENTINEL')
    backend=SimpleNamespace(V2_SERVICES={'snapshots':SimpleNamespace(get=fail)})
    rows, receipt=Q.discovery_input(backend,{'items':[],'snapshot_id':'S','parameters':{}})
    assert 'PRIVATE_CREDENTIAL_SENTINEL' not in str(receipt)
    assert rows==[] and receipt['status']=='PARTIAL'


def test_thin_event_retains_provided_official_link():
    event=source()['items'][0]
    url='https://www.sncouncil.go.kr/record/HwpDownload.do?key=public-document-reference'
    event['speech']['citation'].update(source_url=url,citation_url=url,citation_status='PROVIDED_NOT_FETCHED')
    thin=Q.thin_event(event)
    assert O._event_url(thin,thin['speech'])==url
    assert thin['speech']['citation']['citation_status']=='PROVIDED_NOT_FETCHED'


def test_context_reuses_snapshot_before_bounded_finance_search(monkeypatch):
    full=source(); queries=[]
    async def empty(*args,**kwargs):return {'status':'EMPTY','items':[],'ordinances':[]}
    for name in ('_bill_context','_member_discovery','_policy_context'):monkeypatch.setattr(C,name,empty)
    monkeypatch.setattr(L,'context',empty)
    monkeypatch.setattr(IO,'mention_context',empty)
    async def finance(topic,council,year,limit,search_terms=None):
        queries.append(search_terms)
        return {'status':'PARTIAL' if search_terms else 'EMPTY','items':[{'project_code':'OFFLINEPROJECT','project_name':'소규모 공동주택'}] if search_terms else []}
    monkeypatch.setattr(F,'context',finance)
    async def evidence(**kwargs):
        return {'status':'PARTIAL','parameters':full['parameters'],'snapshot_id':'S1','total_items':1,
                'items':[Q.thin_event(full['items'][0])]}
    backend=SimpleNamespace(V2_SERVICES={'snapshots':SimpleNamespace(get=lambda sid:full)},
        pick_council=lambda q:('031014','경기도 수원시의회',None),council_evidence_bundle=evidence)
    result=asyncio.run(V.context_pack(backend,'빌라가꿈관리소',fiscal_year=2026))
    assert any(terms and terms[0]=='소규모 공동주택' for terms in queries)
    assert result['linked_review']['budget']['discovered_candidates']==1
    assert result['linked_review']['budget']['amounts_verified'] is False
    assert result['search_strategy']['internal_evidence_recovery']['report']['status']=='SNAPSHOT_REUSED'
