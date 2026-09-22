"""Business integration with SYNTHETIC upstream; not MCP SDK/real network tests."""
import asyncio
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import service_v2 as S
import workbench_tools as W
import evidence_core as E
from term_core import extract_terms

class Registry:
    async def list_tools(self): return []

@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.setenv('UIJEONG_STATE_DB',str(tmp_path/'state.db'))
    U=SimpleNamespace(profile_allows=lambda n:False,LITE_TOOLS=set(),mcp=Registry(),RO=None,RO_LOCAL=None,
        PROFILE='test-business-only',API_KEY='',extract_terms=extract_terms,
        clik=SimpleNamespace(_budget=SimpleNamespace(status=lambda:{'test_fixture':True})))
    U.pick_council=lambda c:('062006','합성의회',None)
    def dates(a,b):
        try:
            for d in (a,b):
                if d:dt.date.fromisoformat(d)
            if a and b and a>b:raise ValueError('역전')
            return (a.replace('-','') if a else None,b.replace('-','') if b else None,None)
        except (ValueError,TypeError):return None,None,'날짜 오류'
    U.check_dates=dates
    U.calls=[];U.rows=[];U.errors=[];U.exhausted=True;U.fail=False
    async def listing(keyword,cid,kind,df,dto,unused,max_docs,offset,*args,**kwargs):
        U.calls.append((keyword,df,dto,offset))
        if U.fail:raise RuntimeError('synthetic upstream unavailable')
        selected=[r for r in U.rows if (not df or r['MTG_DE']>=df) and (not dto or r['MTG_DE']<=dto)
                  and keyword in r['MINTS_HTML']]
        return selected[offset:offset+max_docs],len(selected)
    async def details(ids):return [(ident,next(r for r in U.rows if r['DOCID']==ident),None) for ident in ids]
    U.list_minutes=listing;U._gather_details=details
    U.list_state=lambda:{'scanned':len(U.rows),'next_pos':None if U.exhausted else 4,
                         'exhausted':U.exhausted,'errors':U.errors}
    async def site_list(page):return []
    U.site=SimpleNamespace(list_page=site_list)
    state=S.install(U);W.install(U,state['snapshots']);U.state=state
    return U

def row(doc,date,answerer='고령사회정책과장 가상담당자',question='천원국시 매장 확대를 검토해 주십시오.'):
    return {'DOCID':doc,'MTG_DE':date,'RASMBLY_ID':'062006','MINTS_HTML':
        f'<b>○가상위원 위원</b>{question}<br><b>○{answerer}</b>자료를 제출하겠습니다.<br>'}

def run(coro):return asyncio.run(coro)

def test_department_alias_end_to_end(app):
    app.rows=[row('SYNTHETIC1','20241204')]
    r=run(app.council_department_brief('저출산고령사회정책과',source='clik',date_from='2024-01-01',date_to='2024-12-31',
        department_aliases=[{'name':'고령사회정책과','valid_to':'2024-12-31','basis':'합성 조직이력 시험'}]))
    assert r['status']=='COMPLETE' and r['totals']['answered']==1
    assert [x[0] for x in app.calls]==['저출산고령사회정책과','고령사회정책과']
    assert r['answered_items'][0]['answers'][0]['turn_index']>=0
    assert r['public_evidence_snapshot_stored']

@pytest.mark.parametrize('exhausted,expected',[(False,'PARTIAL'),(True,'EMPTY')])
def test_department_empty_and_incomplete_are_different(app,exhausted,expected):
    app.exhausted=exhausted
    r=run(app.council_department_brief('복지정책과',source='clik'))
    assert r['status']==expected and r['totals']['answered']==0

def test_department_failed_source_is_error(app):
    app.fail=True
    assert run(app.council_department_brief('복지정책과',source='clik'))['status']=='ERROR'

def test_repeat_zero_partial_stays_partial(app):
    app.exhausted=False
    r=run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',source='clik'))
    assert r['status']=='PARTIAL' and r['observed_repeat_candidates']==0
    assert not r['same_request_confirmed']

def test_repeat_all_fail_is_error(app):
    app.fail=True
    assert run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',source='clik'))['status']=='ERROR'

def test_rolling_business_windows_not_calendar_defaults(app):
    r=run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',period_mode='rolling_years',source='clik'))
    assert [x[1:3] for x in app.calls]==[('20240921','20241231'),('20250101','20251231'),('20260101','20260921')]
    assert r['status']=='EMPTY'

def test_repeated_word_opposite_demands_stay_candidates(app):
    app.rows=[row('SYN_A','20241204'),row('SYN_B','20250101',question='천원국시 매장 확대는 보류해 주십시오.')]
    r=run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',source='clik'))
    target=next(x for x in r['recurring'] if x['term']=='매장')
    assert target['contrasting_cues_detected'] and not target['same_request_confirmed']
    assert len(r['snapshot_ids'])==2

def test_repeat_department_uses_legacy_alias_in_final_filter(app):
    app.rows=[row('SYN_A','20241204'),row('SYN_B','20250101')]
    r=run(app.council_recurring_issues(department='저출산고령사회정책과',extra_terms=['고령사회정책과'],
        years=2,as_of='2026-09-21',source='clik'))
    assert r['events_examined']==2 and r['recurring']

@pytest.mark.parametrize('kwargs',[
    {'keyword':'천원국시','department':'복지정책과'},
    {'keyword':'천원국시','top':0},
    {'keyword':'천원국시','max_docs_per_year':0},
    {'keyword':'천원국시','source':'unknown'},
    {'keyword':'천원국시','extra_terms':['다른과']},
    {'keyword':'천원국시','years':True},
])
def test_invalid_repeat_never_calls_upstream(app,kwargs):
    assert run(app.council_recurring_issues(**kwargs))['status']=='INVALID_INPUT'
    assert not app.calls

def test_department_continuation_offset_reaches_upstream(app):
    run(app.council_department_brief('복지정책과',source='clik',source_offset=10))
    assert app.calls[0][-1]==10

def test_snapshot_unavailable_is_partial_not_no_data(app,monkeypatch):
    app.rows=[row('SYN_A','20241204')]
    monkeypatch.setattr(app.state['snapshots'],'get',lambda ident:None)
    r=run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',source='clik'))
    assert r['status']=='PARTIAL' and r['snapshot_unavailable']

def test_worksheet_missing_one_id_rejects_whole_selection(app):
    app.rows=[row('SYN_A','20241204')]
    b=run(app.council_evidence_bundle('천원국시',source='clik'))
    r=run(app.council_format_worksheet(form='행정사무감사_답변카드',topic='천원국시',department='고령사회정책과',
        snapshot_id=b['snapshot_id'],event_ids=[b['items'][0]['event_id'],'not-found']))
    assert r['status']=='INVALID_INPUT'

def test_snapshot_scope_applies_to_workbench(app):
    import runtime_security as R
    app.rows=[row('SYN_A','20241204')]
    t=R.REQUEST_SCOPE.set('oauth:synthetic-A')
    try:b=run(app.council_evidence_bundle('천원국시',source='clik'))
    finally:R.REQUEST_SCOPE.reset(t)
    t=R.REQUEST_SCOPE.set('oauth:synthetic-B')
    try:r=run(app.council_get_evidence(b['snapshot_id']))
    finally:R.REQUEST_SCOPE.reset(t)
    assert r['status']=='INVALID_INPUT'

def test_status_not_end_to_end_auth_claim(app):
    r=run(app.council_status())
    assert r['version']==__import__('release_info').VERSION and not r['live_checks']
    assert r['deployment_validation']=='REMOTE_RUNTIME_STATUS_NOT_END_TO_END_AUTH_PROOF'

def test_repeated_candidates_top_truncation_keeps_partial(app):
    app.rows=[row('SYN_A','20241204'),row('SYN_B','20250101')]
    r=run(app.council_recurring_issues(keyword='천원국시',years=2,as_of='2026-09-21',source='clik',top=1))
    assert r['status']=='PARTIAL' and r['omitted_candidate_terms']>0
