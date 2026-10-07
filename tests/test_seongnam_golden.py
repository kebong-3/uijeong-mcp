"""Seongnam acceptance and independent negative controls.

The 2026-09-04 quote was read through production council_read_source on
2026-10-07 UTC. The HTML fixture is a structural reconstruction of that parsed
excerpt, NOT original HTML or a claim of original HTML-byte offsets. Live
checks separately re-fetch the actual document on the deployed release.
"""
import asyncio
import copy
import datetime as dt
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import TypeAdapter

import budget_evidence as B
import dept_core as D
import evidence_core as E
import evidence_quality as G
import finance_context as F
import integrated_workflow as W
import openai_compat as O
import public_server as P
import query_decomposition as Q
import runtime_security as R
import v3_reliability as V
from jachi.client import LawClient
from jachi.config import Settings

QUESTION = '성남시 스마트도시 관련 조례, 2026년 예산현액·본예산/추경 구분, 2026년 의회 발언을 찾아 서로 연결하고 MCP 품질을 검증한다.'
NATURAL = '성남시의회 2026 스마트도시 스마트그린 안전쉼터 이군수'
META = {'DOCID':'CLIKC2912207453426003','RASMBLY_ID':'031013','RASMBLY_NM':'경기도 성남시의회',
        'MTG_DE':'20260904','RASMBLY_NUMPR':'10','RASMBLY_SESN':'312','MTGNM':'예산결산특별위원회','MINTS_ODR':'1'}
QUOTE = '스마트도시과는 뭐 제가 지속적으로 스마트그린 안전쉼터 관련된 언급을 계속하고 있고 제 지역구 중심으로는 체크를 좀 하는 부분이어서 지금 스마트안전그린 쉼터하고 스마트 버스 쉘터 부분하고가 지금 약간 혼재된 느낌으로 하고 있는데 제가 확인하고 있는 바로는 궁극적으로는 대중교통과가 이거를 최종적으로 넘겨받아서 관리하는 쪽으로 갈 것이다라는 얘기를 해요. 맞습니까?'
SOURCE = '○이군수 위원 ' + QUOTE + '    ○AI혁신국장 차광승   예, 맞습니다.'


def record(source=SOURCE):
    return E.make_record(META,E.parse_turns(source),source='CLIK',body_url='https://clik.nanet.go.kr/openapi/minutes.do',body_url_verified=True)


@pytest.mark.parametrize('question',[QUESTION,'성남시의 스마트도시 관련 조례 찾아보고 관련 예산이나 의회발언도 찾아줘 2026년 기준으로',
    '성남시 스마트도시 관련 조례·예산·의회발언을 2026년 기준으로 찾아줘'])
def test_01_topics_exclude_commands(question):
    plan=Q.decompose(question,'성남시')
    assert plan['topic_entities'] == ['스마트도시']
    assert plan['search_terms'] == ['스마트도시','스마트시티']
    assert plan['search_synonyms'] == ['스마트시티']
    assert set(Q.council_search_terms(question)) == {'스마트도시','스마트시티'}
    assert plan['coverage_contract']['semantic_exhaustive'] is False


def test_01_intents_and_explicit_names_are_preserved():
    plan=Q.decompose(QUESTION,'성남시')
    assert set(plan['budget_stages']) == {'current','original','supplementary'}
    assert plan['council_intent'] == ['speech']
    assert 'cross_domain_link' in plan['meta_intent']
    assert 'MCP 품질 검증' in Q.decompose('「MCP 품질 검증」 사업의 예산을 찾아줘')['topic_entities']
    workflow=W.local_workflow_plan(QUESTION,as_of='2026-10-07')
    assert workflow['status']=='PLAN_ONLY'
    assert workflow['decomposition']['jurisdiction']=='성남시'
    council=next(s for s in workflow['steps'] if s['domain']=='council')
    assert council['executable_calls'][0]['arguments']['date_to']=='2026-10-07'
    assert council['executable_calls'][0]['arguments']['keyword']=='스마트도시'


@pytest.fixture
def fiscal(monkeypatch):
    monkeypatch.setenv('LOFIN_API_KEY','OFFLINE-UNIT-NOT-A-KEY')
    monkeypatch.setattr(V,'today',lambda:dt.date(2026,10,7))
    calls=[]
    def row(code):
        return {'fyr':'2026','exe_ymd':'20261006','laf_hg_nm':'경기성남시','laf_cd':'4112000',
                'dbiz_cd':code,'dbiz_nm':'스마트도시 시험사업 '+code,'acnt_dv_nm':'일반회계',
                'bdg_cash_amt':'1000','ep_amt':'500'}
    async def request(params):
        calls.append(dict(params))
        if 'dbiz_nm' not in params:
            return {'rows':[],'total_count':0,'result_code':'INFO-200'} if params['exe_ymd']=='20261007' else {'rows':[row('probe')],'total_count':1}
        codes = ['A','B','C'] if params['dbiz_nm']=='스마트도시' else ['C','D','E'] if params['dbiz_nm']=='스마트시티' else []
        return {'rows':[row(code) for code in codes],'total_count':len(codes),'result_code':'INFO-000'}
    monkeypatch.setattr(F,'_request',request)
    return calls


@pytest.mark.parametrize('topic',['스마트도시','스마트도시 스마트시티 스마트도시 조성'])
def test_02_synonyms_are_separate_union_with_no_duplicate_projects(fiscal,topic):
    result=asyncio.run(V.finance_context(topic,'성남시',2026,10,snapshot_date='20261007'))
    assert [r['dbiz_nm'] for r in fiscal if 'dbiz_nm' in r] == ['스마트도시','스마트시티']
    assert {r['project_code'] for r in result['items']} == {'A','B','C','D','E'}
    assert len(result['items']) == 5
    assert result['date_resolution']['mixed_dates'] is False
    assert result['query']['snapshot_date']=='20261006'
    assert result['search_strategy']['combination']=='BOUNDED_SYNONYM_UNION'
    assert len(result['search_strategy']['planned_queries'])<=4


@pytest.mark.parametrize('stage',['original','supplementary','draft','settlement'])
def test_03_current_amounts_never_promoted_to_requested_adopted_stage(fiscal,stage):
    result=asyncio.run(V.finance_context('스마트도시','성남시',2026,10,snapshot_date='20261007',budget_stage=stage))
    assert result['status']=='PARTIAL'
    assert result['budget_basis']['requested_stage']==stage
    assert result['budget_basis']['returned_stage']=='current'
    assert result['budget_basis']['requested_stage_verified'] is False
    assert all(item['budget_stage']=='current' for item in result['items'])


def test_04_unit_unknown_blocks_normalization_and_final_gate(fiscal):
    finance=asyncio.run(V.finance_context('스마트도시','성남시',2026,10,snapshot_date='20261007'))
    assert finance['unit_metadata']['unit_verified'] is False
    assert finance['numeric_normalization']=='BLOCK_NUMERIC_NORMALIZATION'
    result=G.final_quality_gate({'status':'PARTIAL','finance_context':finance})
    assert result['numeric_normalization']=='BLOCK_NUMERIC_NORMALIZATION'
    assert any('단위 미검증 원시값' in text for text in result['required_answer_qualifiers'])
    assert result['verified_facts'] is False
    assert result['policy_entity']['same_project_verified'] is False


@pytest.fixture
def ordinance(monkeypatch):
    calls=[]
    title='성남시 스마트도시 조성 및 운영 조례'
    rows=[{'자치법규ID':'111','자치법규일련번호':'222','자치법규명':'성남시 스마트도시 지원 조례', '지자체기관명':'경기도 성남시'},
          {'자치법규ID':'2152882','자치법규일련번호':'2013375','자치법규명':title, '지자체기관명':'경기도 성남시'}]
    async def request(self,endpoint,params,**kwargs):
        calls.append(params)
        return {'OrdinSearch':{'totalCnt':'2','law':rows}}, {'source_state':'fixture'}
    # Supply normalized result rows separately; this test isolates query/ranking,
    # not the upstream JSON decoder which has existing independent tests.
    import jachi.client as C
    monkeypatch.setattr(C,'listing_rows',lambda data,kind:[{'document_id':r['자치법규ID'],'mst':r['자치법규일련번호'],
        'title':r['자치법규명'],'jurisdiction':r['지자체기관명'],'parent_article':'','ordinance_article':''} for r in rows])
    monkeypatch.setattr(C,'total_count',lambda data:2)
    monkeypatch.setattr(LawClient,'request',request)
    return calls,title


def test_05_exact_title_first_not_an_unverified_first_broad_hit(ordinance):
    calls,title=ordinance
    result=asyncio.run(LawClient().search(title,jurisdiction='성남시',max_pages=1))
    assert result['results'][0]['document_id']=='2152882'
    assert result['results'][0]['mst']=='2013375'
    assert result['results'][0]['match_basis']=='EXACT_TITLE'
    assert calls[0]['query']==title


def test_06_locality_sent_upstream_not_nationwide_postfilter(ordinance):
    calls,_=ordinance
    result=asyncio.run(LawClient().search('스마트도시',jurisdiction='성남시',max_pages=1))
    assert calls[0]['query']=='성남시 스마트도시'
    assert result['search_strategy']['jurisdiction_applied_upstream'] is True
    assert result['results'][0]['jurisdiction_match'] is True
    assert not result['search_strategy']['national_fallback_used']


def test_07_standard_search_uses_the_same_topics_dates_and_actual_speakers():
    O._SEARCH_CACHE.clear()
    calls=[]
    async def bundle(**kwargs):
        calls.append(kwargs)
        return {'status':'PARTIAL','items':E.record_events(record(),'스마트도시','발언')}
    tools=O.build_tools(SimpleNamespace(council_evidence_bundle=bundle))
    result=asyncio.run(tools['search'](NATURAL))
    assert result.results
    assert calls[0]['keyword']=='스마트도시'
    assert calls[0]['date_from']=='2026-01-01'
    assert '스마트그린 안전쉼터' in calls[0]['search_terms']
    assert '이군수' in result.results[0].title
    assert '2026' in result.results[0].title
    assert 'CLIKC2912207453426003' in str(O._decode_id(result.results[0].id))


def test_08_inline_ascii_executive_is_separate_answer_with_exact_plain_span():
    turns=E.parse_turns(SOURCE)
    assert len(turns)==2
    assert turns[0]['label']=='이군수 위원'
    assert turns[1]['label']=='AI혁신국장 차광승'
    assert turns[1]['text']=='예, 맞습니다.'
    assert turns[0]['agenda']==turns[1]['agenda']
    pairs=E.build_qa_pairs(turns,'스마트도시')
    assert pairs[0]['answers'][0]['label']=='AI혁신국장 차광승'
    text=E.plain_text(SOURCE)
    for turn in turns:
        assert text[turn['char_start']:turn['char_end']].strip()==turn['text']
        assert turn['source_span']['basis']=='html_to_plain_text'


@pytest.mark.parametrize('job',['AI혁신국장','AI반도체과장','ICT전략과장','3D공간정보과장'])
def test_08_ascii_and_digit_titles_generalize_beyond_single_regression(job):
    result=E.parse_turns('○김검증 위원 자료를 제출하겠습니까? ○'+job+' 이검증 제출하겠습니다.')
    assert len(result)==2
    assert result[1]['role']=='executive'


def test_08_unknown_bullets_and_formal_reports_do_not_become_fake_answers():
    assert len(E.parse_turns('○김검증 위원 다음 항목입니다. ○AI 기반 지원사업은 장기 과제입니다.'))==1
    turns=E.parse_turns('○김검증 위원 사업의 운영계획은 무엇입니까? ○AI혁신국장 이검증 업무보고를 드리겠습니다.')
    assert E.build_qa_pairs(turns)[0]['answers']==[]


def test_09_explicit_department_question_with_bureau_response_is_classified():
    events=E.record_events(record(),'스마트도시','질의답변')
    result=D.classify_department_events(events,'스마트도시과')
    assert len(result['answered'])==1
    assert result['answered'][0]['department_match_basis']=='PARENT_BUREAU_CONTEXT'
    assert result['answered'][0]['organizational_relationship_verified'] is False


def test_09_no_unstated_organizational_inference():
    event=E.record_events(record('○김검증 위원 청년 지원은 어떻게 합니까? ○AI혁신국장 이검증 검토하겠습니다.'),'','질의답변')
    assert not D.classify_department_events(event,'스마트도시과')['answered']


def test_09_announced_department_section_is_preserved_with_source_locator():
    events=E.record_events(record('○위원장 김검증 다음은 스마트도시과 소관 심사를 하겠습니다. ○이검증 위원 운영 방안은 무엇입니까? ○행정국장 박검증 현황을 제출하겠습니다.'),'','질의답변')
    rows=D.classify_department_events(events,'스마트도시과')['answered']
    assert rows and rows[0]['department_match_basis']=='AGENDA_SECTION'
    assert rows[0]['question']['department_context']['turn_index']==0


def test_10_meeting_metadata_duplicates_keep_all_alternates_without_body_claim():
    rows=[{**META,'DOCID':str(i)} for i in range(5)]
    groups=G.meeting_groups(rows)
    assert len(groups)==1
    assert groups[0]['alternate_docids']==['1','2','3','4']
    assert groups[0]['body_equivalence_verified'] is False
    assert len(G.meeting_groups([{'DOCID':'1'},{'DOCID':'2'}]))==2
    assert len(G.meeting_groups([META,{**META,'MTG_DE':'20260905'}]))==2


def test_11_large_bundle_keeps_representatives_and_exact_continuation():
    events=E.record_events(record(),'스마트도시','질의답변')
    rows=[]
    for i in range(20):
        event=copy.deepcopy(events[0]);event['event_id']=str(i)
        event['question']['text']='스마트도시 관련 발언입니다. '*1000
        rows.append(event)
    payload={'status':'PARTIAL','snapshot_id':'a'*64,'items':rows,'total_items':20,'item_offset':0,'records':[],
             'coverage':[],'coverage_summary':{},'errors':[],'parameters':{'keyword':'스마트도시'}}
    compact=G.compact_bundle(payload)
    assert 3 <= len(compact['items']) <= 5
    assert compact['total_items']==20
    assert compact['next_item_offset']==len(compact['items'])
    assert compact['continuation']['arguments']['item_offset']==compact['next_item_offset']
    assert len(json.dumps(compact,ensure_ascii=False))<30000
    assert payload['items'][0]['question']['text'].endswith(' ')
    assert compact['items'][0]['question']['excerpt']['partial'] is True


def test_11_large_snapshot_compression_is_lossless_scoped_and_bounded(tmp_path):
    store=R.SnapshotStore(tmp_path/'state.sqlite',scope='test',max_bytes=1024,max_uncompressed_bytes=16000,compress_large=True)
    payload={'items':[{'text':'공식 공개 원문'*600}]}
    ident=store.put(payload,source_kind='OFFICIAL_FETCHED')
    assert store.get(ident)==payload
    assert R.SnapshotStore(tmp_path/'state.sqlite',scope='other').get(ident) is None
    with pytest.raises(R.SecurityError):store.put({'text':'가'*20000},source_kind='OFFICIAL_FETCHED')
    with sqlite3.connect(tmp_path/'state.sqlite') as connection:
        connection.execute('UPDATE snapshots SET payload=? WHERE id=?',('ZJ1:999999999:bad:data',ident))
    with pytest.raises(R.SecurityError):store.get(ident)


def test_12_empty_sample_does_not_mean_runtime_down():
    result=G.integration_health({'release_verification':{'status':'MATCH'}},{'finance365':{'status':'EMPTY'}})
    assert result['runtime_status']=='HEALTHY'
    assert result['integration_status']['finance365']['state']=='HEALTHY_BUT_SAMPLE_EMPTY'
    assert result['integration_status']['law']['state']=='NO_CHECK_SINCE_RESTART'
    assert result['health_status']=='HEALTHY_WITH_WARNINGS'


def test_schema_matches_real_public_caps(monkeypatch):
    monkeypatch.setenv('UIJEONG_AUTH_MODE','public')
    monkeypatch.setenv('UIJEONG_PUBLIC_READONLY','true')
    import uijeong_mcp as U
    monkeypatch.setattr(U, 'PROFILE', U.PROFILE)
    monkeypatch.setattr(U, 'mcp', U.mcp)
    server=P.build_server(U)
    tools=asyncio.run(server.list_tools());schemas={t.name:t.inputSchema for t in tools}
    assert len(tools)==40
    assert schemas['council_evidence_bundle']['properties']['max_docs']['maximum']==6
    assert schemas['council_read_source']['properties']['max_chars']['maximum']==16000
    assert schemas['ordinance_get_document']['properties']['max_chars']['maximum']==5000


def test_public_document_keys_not_credentials_and_markdown_stays_valid(monkeypatch):
    url='https://www.sncouncil.go.kr/record/HwpDownload.do?key=PUBLIC123'
    assert R.redact_secrets('[원문]('+url+')')=='[원문]('+url+')'
    bad='https://clik.nanet.go.kr/openapi/minutes.do?key=SECRET123'
    assert 'SECRET123' not in R.redact_secrets('[원문]('+bad+')')
    assert R.redact_secrets('[원문]('+bad+')').endswith(')')
    monkeypatch.setenv('CLIK_API_KEY','PUBLIC123')
    assert 'PUBLIC123' not in R.redact_secrets(url)
    assert 'TOKEN123' not in R.redact_secrets('https://www.sncouncil.go.kr/record/HwpDownload.do?key=PUBLIC123&token=TOKEN123')
