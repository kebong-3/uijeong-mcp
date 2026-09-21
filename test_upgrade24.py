"""v2.4 regression counterexamples. All speeches/persons/tokens are synthetic."""
import asyncio
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import time
import httpx
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import period_core as P
import coverage_core as C
import department_aliases as A
import dept_core as D
import evidence_core as E
import runtime_security as R
from term_core import extract_terms
from oauth_resource import OAuthConfig, AuthFailure, validate_introspection, IntrospectionVerifier

TODAY=dt.date(2026,9,21)

def ev(question='천원국시 매장 확대를 검토해 주십시오.',label='고령사회정책과장 가상담당자',date='20241204',doc='FAKE1'):
    text=f'<b>○가상위원 위원</b>{question}<br><b>○{label}</b>자료를 제출하겠습니다.<br>'
    record=E.make_record({'DOCID':doc,'RASMBLY_ID':'062006','MTG_DE':date},E.parse_turns(text),source='fixture',source_kind='SYNTHETIC')
    return E.record_events(record,'','질의답변'),E.record_events(record,'','약속')


def test_rolling_two_years_includes_three_calendar_segments():
    p=P.resolve_period(years=2,period_mode='rolling_years',as_of='2026-09-21',today=TODAY)
    assert (p['date_from'],p['date_to'])==('2024-09-21','2026-09-21')
    assert [w['meeting_year'] for w in p['windows']]==[2024,2025,2026]
    assert p['windows'][0]['date_from']=='2024-09-21'


def test_calendar_period_is_not_rolling():
    p=P.resolve_period(years=2,as_of='2026-09-21',today=TODAY)
    assert (p['date_from'],p['date_to'])==('2024-01-01','2025-12-31')


def test_leap_day_clamped_and_explicit_dates_take_priority():
    p=P.resolve_period(years=1,period_mode='rolling_years',as_of='2024-02-29',today=TODAY)
    assert p['date_from']=='2023-02-28'
    p=P.resolve_period(years=5,date_from='2024-09-21',date_to='2026-09-21',today=TODAY)
    assert p['mode']=='explicit_dates' and p['years_applied'] is None


@pytest.mark.parametrize('kwargs',[{'years':True},{'years':0},{'years':6},{'as_of':'2026-09-22'},
 {'as_of':'20260921'},{'period_mode':'recent'},{'date_from':'2024-09-21'},
 {'date_from':'2025-01-01','date_to':'2024-01-01'},
 {'date_from':'2024-02-30','date_to':'2026-09-21'},
 {'date_from':'2024-01-01','date_to':'2026-09-22'},
 {'date_from':'2000-01-01','date_to':'2026-09-21'}])
def test_period_input_errors(kwargs):
    with pytest.raises(ValueError):P.resolve_period(today=TODAY,**kwargs)


@pytest.mark.parametrize('upstream,count,expected', [('PARTIAL',0,'PARTIAL'),('ERROR',0,'ERROR'),
 ('COMPLETE',0,'EMPTY'),('COMPLETE',1,'COMPLETE'),('EMPTY',0,'EMPTY')])
def test_partial_not_overwritten(upstream,count,expected):
    assert C.observed_status(count,upstream=upstream)==expected


def test_no_repeat_does_not_erase_source_failure():
    assert C.combine_statuses(['ERROR','EMPTY'],0)=='PARTIAL'
    assert C.combine_statuses(['ERROR','ERROR'],0)=='ERROR'
    assert C.combine_statuses(['EMPTY','EMPTY'],0)=='EMPTY'


def alias():
    return A.normalize_aliases('저출산고령사회정책과',[{'name':'고령사회정책과','valid_from':'2024-01-01',
                 'valid_to':'2024-12-31','basis':'합성 부서 이력 시험'}])


def test_alias_is_applied_to_final_match_and_preserves_quote():
    qa,_=ev()
    assert not D.classify_department_events(qa,'저출산고령사회정책과')['answered']
    row=D.classify_department_events(qa,'저출산고령사회정책과',alias())['answered'][0]
    assert row['matched_department_names']==['고령사회정책과']
    assert row['answers'][0]['text']==qa[0]['answers'][0]['text']
    assert row['answers'][0]['turn_index']==qa[0]['answers'][0]['turn_index']
    assert row['provenance']['source_kind']=='SYNTHETIC'


def test_alias_validity_rejects_outside_and_keeps_undated_for_review():
    qa,_=ev(date='20250101')
    assert not D.classify_department_events(qa,'저출산고령사회정책과',alias())['answered']
    qa,_=ev(date='')
    groups=D.classify_department_events(qa,'저출산고령사회정책과',alias())
    assert not groups['answered'] and len(groups['alias_date_unresolved'])==1


def test_alias_filter_and_commitments_share_same_rule():
    qa,f=ev()
    assert D.event_touches_department(qa[0],'저출산고령사회정책과',alias())
    assert D.department_commitments(f,'저출산고령사회정책과',alias())


@pytest.mark.parametrize('aliases',[[{}],[{'name':'과','basis':'x'}],[{'name':'이전과'}],
 [{'name':'이전과','basis':'x','valid_from':'2025-01-01','valid_to':'2024-01-01'}],
 [{'name':'이전과','basis':'x','unknown':True}],['이전과']])
def test_invalid_aliases_are_not_silently_accepted(aliases):
    with pytest.raises(ValueError):A.normalize_aliases('현재과',aliases)


def test_legacy_aliases_not_silently_truncated():
    with pytest.raises(ValueError):A.normalize_aliases('현재과',legacy_terms=['예전과','이전과','과거과'])
    assert A.normalize_aliases('현재과',legacy_terms=['이전과'])[0]['verified_by_server'] is False


def test_same_word_opposite_request_is_not_same_request():
    qa1,_=ev(date='20240101',doc='A')
    qa2,_=ev('천원국시 매장 확대는 보류해 주십시오.',date='20250101',doc='B')
    table=D.recurring_terms(qa1+qa2,extract_terms,min_years=2)
    row=next(r for r in table['items'] if r['term']=='매장')
    assert row['contrasting_cues_detected'] and row['same_request_confirmed'] is False
    assert row['classification']=='REPEATED_TOPIC_CANDIDATE'
    assert {c['metadata']['meeting_date'] for c in row['citations']}=={'20240101','20250101'}


def test_same_word_same_cue_still_not_confirmed_same_request():
    a,_=ev(date='20240101',doc='A');b,_=ev(date='20250101',doc='B')
    row=D.recurring_terms(a+b,extract_terms,min_years=2)['items'][0]
    assert not row['same_request_confirmed']


def test_identical_commitment_in_different_meetings_is_not_deleted():
    _,a=ev(date='20240101',doc='A');_,b=ev(date='20250101',doc='B')
    assert len(D.department_commitments(a+b,'고령사회정책과'))==2


def test_utf8_bytes_not_character_count(tmp_path):
    s=R.SnapshotStore(tmp_path/'s.db',max_total_bytes=110)
    a=s.put({'text':'한'*25})
    with pytest.raises(R.SecurityError):s.put({'text':'한'*25})
    assert s.get(a)


def test_http_principals_cannot_reuse_each_others_snapshots(tmp_path):
    s=R.SnapshotStore(tmp_path/'s.db',bind_request_scope=True)
    t=R.REQUEST_SCOPE.set('oauth:user-A')
    try:ident=s.put({'public':'합성근거'})
    finally:R.REQUEST_SCOPE.reset(t)
    t=R.REQUEST_SCOPE.set('oauth:user-B')
    try:assert s.get(ident) is None and s.delete(ident) is False
    finally:R.REQUEST_SCOPE.reset(t)
    t=R.REQUEST_SCOPE.set('oauth:user-A')
    try:assert s.get(ident)
    finally:R.REQUEST_SCOPE.reset(t)


def test_per_user_storage_still_obeys_global_cap(tmp_path):
    s=R.SnapshotStore(tmp_path/'s.db',bind_request_scope=True,max_entries=1)
    t=R.REQUEST_SCOPE.set('oauth:a')
    try:s.put({'a':1})
    finally:R.REQUEST_SCOPE.reset(t)
    t=R.REQUEST_SCOPE.set('oauth:b')
    try:
        with pytest.raises(R.SecurityError):s.put({'b':1})
    finally:R.REQUEST_SCOPE.reset(t)


def cfg(cache=0):
    return OAuthConfig('https://id.example.test','https://mcp.example.test/mcp',
                       'https://id.example.test/introspect','test-client','test-secret',cache_seconds=cache)


def claims():
    return {'active':True,'iss':cfg().issuer,'aud':[cfg().resource],'exp':2000,
            'sub':'synthetic-user','scope':'council:read','token_type':'Bearer'}


@pytest.mark.parametrize('field,value', [('active',False),('active','true'),('iss','https://other.example.test'),
 ('aud','https://other.example.test'),('exp',999),('exp',True),('exp',float('nan')),
 ('nbf',1100),('sub',''),('token_type','refresh_token'),('token_type',[]),('scope','other:read')])
def test_introspection_invalid_claims_fail_closed(field,value):
    data=claims();data[field]=value
    with pytest.raises(AuthFailure):validate_introspection(data,cfg(),1000)


def test_verified_identity_is_stable_and_not_raw_subject():
    v=validate_introspection(claims(),cfg(),1000)
    assert 'synthetic-user' not in v['identity'] and v['identity'].startswith('oauth:')


def test_scope_failure_is_403():
    data=claims();data['scope']=''
    with pytest.raises(AuthFailure) as e:validate_introspection(data,cfg(),1000)
    assert e.value.http_status==403


def test_introspection_post_never_forwards_on_redirect(monkeypatch):
    async def dns(host):pass
    monkeypatch.setattr(R,'_public_dns',dns)
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(302,headers={'location':'https://evil.example.test/'})
    v=IntrospectionVerifier(cfg(),transport=httpx.MockTransport(handler),clock=lambda:1000)
    with pytest.raises(AuthFailure) as e:asyncio.run(v.verify('synthetic-token'))
    assert e.value.http_status==503 and len(seen)==1
    assert seen[0].method=='POST' and 'synthetic-token' not in str(seen[0].url)


def test_introspection_revocation_checked_each_request_by_default(monkeypatch):
    async def dns(host):pass
    monkeypatch.setattr(R,'_public_dns',dns)
    count=[0]
    def handler(request):
        count[0]+=1
        return httpx.Response(200,json=claims() if count[0]==1 else {'active':False})
    async def go():
        v=IntrospectionVerifier(cfg(),transport=httpx.MockTransport(handler),clock=lambda:1000)
        await v.verify('synthetic-token')
        with pytest.raises(AuthFailure):await v.verify('synthetic-token')
    asyncio.run(go());assert count[0]==2


def test_introspection_network_error_no_secret_in_error(monkeypatch):
    async def dns(host):raise OSError('synthetic-secret-must-not-be-revealed')
    monkeypatch.setattr(R,'_public_dns',dns)
    with pytest.raises(AuthFailure) as e:
        asyncio.run(IntrospectionVerifier(cfg()).verify('synthetic-token'))
    assert e.value.http_status==503 and 'secret' not in str(e.value)


def test_public_metadata_and_health_do_not_open_mcp():
    called=[]
    async def inner(scope,receive,send):called.append(True)
    policy={'hosts':['mcp.example.test'],'origins':[],'token':'','auth_mode':'oauth','oauth':cfg()}
    async def get(path):
        g=R.HTTPGuard(inner,policy);sent=[]
        async def send(x):sent.append(x)
        async def receive():return {'type':'http.request','body':b''}
        await g({'type':'http','method':'GET','path':path,'headers':[(b'host',b'mcp.example.test')]},receive,send)
        return sent
    for path in ['/healthz','/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-protected-resource']:
        assert asyncio.run(get(path))[0]['status']==200
    result=asyncio.run(get('/mcp'))
    assert result[0]['status']==401 and not called
    assert any(k==b'www-authenticate' and b'resource_metadata' in v for k,v in result[0]['headers'])


def test_oauth_config_cannot_fall_back_to_public_local_mode(monkeypatch):
    monkeypatch.setenv('UIJEONG_BIND_HOST','0.0.0.0')
    monkeypatch.setenv('UIJEONG_AUTH_MODE','local')
    with pytest.raises(R.SecurityError):R.http_policy()

def test_invalid_meeting_date_not_a_valid_year():
    rows,_=ev(date='20241340')
    table=D.recurring_terms(rows,extract_terms,min_years=1)
    assert table['undated_events']==1 and not table['items']

def test_recurring_top_limit_discloses_omitted_candidates():
    a,_=ev(date='20240101',doc='A');b,_=ev(date='20250101',doc='B')
    table=D.recurring_terms(a+b,extract_terms,min_years=2,top=1)
    assert table['total_candidate_terms']>1 and table['omitted_candidate_terms']==table['total_candidate_terms']-1
