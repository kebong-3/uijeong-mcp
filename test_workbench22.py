import asyncio,copy,json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import council_workbench as C
import evidence_core as E
import response_budget as B


def payload():
 body='○김가상 위원: 성인지예산 교육 참여자는 몇 명입니까?\n○기획과장 이가상: 100명입니다. 자료를 10월까지 제출하겠습니다.'
 record=E.make_record({'DOCID':'D22','RASMBLY_ID':'062006','MTG_DE':'20250101'},E.parse_turns(body),source='CLIK')
 return {'status':'PARTIAL','items':E.record_events(record,'성인지예산','질의답변'),
         'followup_items':E.record_events(record,'성인지예산','약속'),'coverage':[{'source':'CLIK','parsed':1,'exhausted':False}]}

@pytest.mark.parametrize('kind',list(C.PURPOSES))
def test_plan_per_purpose(kind):
 p=C.plan_session('기획실',['성인지예산'],kind,'2026-10-01')
 assert p['schedule'][0]['suggested_date']=='2026-09-17'
 assert p['topic_tasks'][0]['checklist'] and '법정' in p['schedule_basis']
 assert p['stored'] is False

@pytest.mark.parametrize('topics',[[],['a']*11,None,'예산'])
def test_plan_rejects_invalid_topics(topics):
 with pytest.raises(ValueError):C.plan_session('기획실',topics)

def test_card_only_known_event_and_no_fact_promotion():
 p=payload();ident=p['items'][0]['event_id']
 card=C.build_issue_card(p,[ident],'성인지예산','기획실','결산심사',[{'id':'F1','text':'교육 참여 100명','as_of':'2026-09-19'}])
 assert card['current_facts'][0]['source_kind']=='USER_PROVIDED'
 assert card['missing_documents']==['document_ref'] and not card['ready_for_submission']
 assert all(s['draft'] is None for s in card['answer_sections'])
 with pytest.raises(ValueError):C.build_issue_card(p,['not-real'],'주제','부서','업무보고',[])

def test_draft_numeric_presence_not_truth():
 r=C.review_answer('2026년 참여자는 100명입니다. 반드시 모두 지원하겠습니다.',
 [{'id':'F1','text':'2025년 참여자는 100명입니다.','document_ref':'보고서 p.3','as_of':'2025-12-31'}],[])
 n=next(n for n in r['numeric_checks'] if n['token']=='100명')
 assert n['candidate_fact_ids']==['F1'] and '미검증' in n['status']
 assert any(n['token']=='2026년' and not n['candidate_fact_ids'] for n in r['numeric_checks'])
 assert r['expression_checks'] and r['ready_for_submission'] is False

def test_claim_anchor_and_support_are_independently_checked():
 facts=[{'id':'F','text':'참여자는 100명입니다.','document_ref':'보고서','as_of':'2026-09-19'}]
 r=C.review_answer('참여자는 100명입니다.',facts,[{'text':'참여자는 100명입니다.','fact_id':'F','support_excerpt':'100명'}])
 assert not r['claim_checks'][0]['issues']
 bad=C.review_answer('참여자는 100명입니다.',facts,[{'text':'완료했습니다.','fact_id':'F','support_excerpt':'200명'}])
 assert len(bad['claim_checks'][0]['issues'])==2

def test_duplicate_claim_requires_position():
 facts=[{'id':'F','text':'검토하겠습니다.'}]
 c={'text':'검토하겠습니다.','fact_id':'F','support_excerpt':'검토하겠습니다.'}
 draft='검토하겠습니다. 검토하겠습니다.'
 assert C.review_answer(draft,facts,[c])['claim_checks'][0]['located_in_draft'] is False
 assert C.review_answer(draft,facts,[dict(c,start_char=0)])['claim_checks'][0]['located_in_draft'] is True

def test_completion_without_evidence_is_not_verified():
 p=payload();ident=p['followup_items'][0]['event_id']
 r=C.review_followups(p,[{'event_id':ident,'reported_status':'완료보고'}],'2026-09-19')
 assert r['items'][0]['review_status']=='완료보고·증빙 보완 필요'
 assert r['items'][0]['fulfillment_verified'] is False

def test_complete_fields_still_not_proof_of_fulfillment():
 p=payload();ident=p['followup_items'][0]['event_id']
 update={'event_id':ident,'reported_status':'완료보고','evidence':[{'document_ref':'제출공문','excerpt':'자료 제출','reviewer':'담당자','checked_at':'2026-09-18'}]}
 row=C.review_followups(p,[update],'2026-09-19')['items'][0]
 assert '구비' in row['review_status'] and not row['fulfillment_verified']

def test_deadline_needs_explicit_basis_and_no_default_from_october():
 p=payload();ident=p['followup_items'][0]['event_id']
 r=C.review_followups(p,[{'event_id':ident}],'2026-09-19')
 assert r['items'][0]['due_date'] is None
 with pytest.raises(ValueError):C.review_followups(p,[{'event_id':ident,'due_date':'2026-09-10'}],'2026-09-19')
 row=C.review_followups(p,[{'event_id':ident,'due_date':'2026-09-10','due_basis':'담당자가 정한 회신일'}],'2026-09-19')['items'][0]
 assert row['days_past_due']==9 and '미이행' not in row['attention']

def test_followup_rejects_future_review_and_unknown_id():
 p=payload();ident=p['followup_items'][0]['event_id']
 with pytest.raises(ValueError):C.review_followups(p,[{'event_id':'unknown'}],'2026-09-19')
 with pytest.raises(ValueError):C.review_followups(p,[{'event_id':ident,'evidence':[{'checked_at':'2026-09-20'}]}],'2026-09-19')

def test_figures_exact_decimals_zero_and_wrong_report():
 data=[{'name':'사업A','unit':'천원','current':'27.95','previous':'19.18','reported_change':'8.70'},
       {'name':'사업B','unit':'원','budget':0,'executed':100}]
 r=C.check_figures(data)['items']
 assert r[0]['change']=='8.77' and r[0]['reported_change_matches'] is False
 assert r[1]['execution_rate_pct'] is None and r[1]['unspent']=='-100'

@pytest.mark.parametrize('bad',['NaN','Infinity','1,000','1e100','0.0000001',True,3.2])
def test_figure_input_rejects_unsafe_numbers(bad):
 with pytest.raises(ValueError):C.check_figures([{'name':'사업','unit':'원','current':bad,'previous':1}])


def test_budget_repaired_items_and_catalogue_offsets():
 items=[{'id':i,'text':'가'*1500} for i in range(30)]
 p={'status':'PARTIAL','snapshot_id':'x'*64,'item_offset':40,'next_item_offset':70,'items':items}
 b=B.apply_budget(p,8000)
 assert b['next_item_offset']==40+len(b['items']) and b['next_item_offset']<70
 p={'status':'COMPLETE','offset':20,'next_offset':None,'sources':items}
 b=B.apply_budget(p,8000)
 assert b['next_offset']==20+len(b['sources'])


def test_budget_turns_can_be_reassembled_without_missing_characters():
 turns=E.parse_turns(''.join(f'<b>○기획과장 이가상</b> 발언{i} '+('가나다라'*500)+'<br>' for i in range(9)))
 expected=''.join(t['text'] for t in turns);got=[];start=char=0
 for _ in range(100):
  raw=E.read_page(turns,start_turn=start,start_char=char,max_turns=30,max_chars=24000)
  raw.update(ref='D22',source_kind='OFFICIAL_FETCHED',meta={'description':'관측'*1000})
  b=B.apply_budget(raw,8000)
  assert B.size_of(b)<=8000
  got.extend(t['text'] for t in b.get('turns',[]))
  nxt=b.get('next_start_turn')
  if nxt is None:break
  assert (nxt,b['next_start_char'])!=(start,char)
  start,char=nxt,b['next_start_char']
 assert ''.join(got)==expected


def test_oversized_protected_message_cannot_breach_budget():
 b=B.apply_budget({'status':'ERROR','message':'가'*100000,'items':[]},8000)
 assert B.size_of(b)<=8000 and b['status']=='ERROR'


def test_quote_original_hash_not_mislabelled_as_display_hash():
 p={'status':'COMPLETE','items':[{'question':{'text':'가나다라'*2000,'quote_sha256':'a'*64}}]}
 b=B.apply_budget(p,8000)
 q=b['items'][0]['question']
 assert q['quote_sha256']=='a'*64 and q['text_display']['source_locator_unchanged']
 assert q['text_display']['sha256']!='a'*64

def test_end_to_end_issue_and_followup_through_mcp(monkeypatch):
 import uijeong_mcp as U
 p=payload();p['parameters']={'keyword':'성인지예산'}
 monkeypatch.setattr(U.V2_SERVICES['snapshots'],'get',lambda ident:copy.deepcopy(p) if ident=='f'*64 else None)
 async def run():
  first=await U.mcp.call_tool('council_get_evidence',{'snapshot_id':'f'*64})
  ident=first.structuredContent['items'][0]['event_id']
  card=await U.mcp.call_tool('council_build_issue_card',{'snapshot_id':'f'*64,'event_ids':[ident],'topic':'성인지예산','department':'기획실'})
  assert card.structuredContent['ready_for_submission'] is False
  follow=await U.mcp.call_tool('council_get_evidence',{'snapshot_id':'f'*64,'collection':'followup_items'})
  fid=follow.structuredContent['items'][0]['event_id']
  reviewed=await U.mcp.call_tool('council_review_followups',{'snapshot_id':'f'*64,'updates':[{'event_id':fid,'reported_status':'완료보고'}],'as_of':'2026-09-19'})
  assert reviewed.structuredContent['items'][0]['fulfillment_verified'] is False
 asyncio.run(run())

def test_work_profile_is_core_plus_practice_tools(monkeypatch):
 from test_final_hardening import _tools
 names,U=_tools('work',monkeypatch)
 assert names==U.CORE_TOOLS|U.WORKBENCH_TOOLS|U.DEPARTMENT_TOOLS and len(names)==18

def test_negative_value_is_not_silently_positive():
 r=C.review_answer('총100명, 감소액 -10억원입니다.',[{'id':'F','text':'100명, 10억원'}],[])
 row=next(x for x in r['numeric_checks'] if x['token']=='-10억원')
 assert row['candidate_fact_ids']==[]
 assert any(x['token']=='100명' for x in r['numeric_checks'])


def test_plan_keeps_explicit_council_in_search():
 import council_workbench as C
 result=C.plan_session('기획실',['예산'],council='서울 광진구')
 assert result['council']=='서울 광진구'
 assert result['topic_tasks'][0]['search']['arguments']['council']=='서울 광진구'


def test_figure_ratio_at_accepted_numeric_limits():
 result=C.check_figures([{'name':'경계','unit':'원','current':'1000000000000000000','previous':'0.000001'}])
 assert result['items'][0]['change_rate_pct']=='99999999999999999999999900.00'
