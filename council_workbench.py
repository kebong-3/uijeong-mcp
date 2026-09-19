"""Local, non-persistent council preparation tools. Never approve an official answer."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import json
import re
from typing import Any

PURPOSES = {
 '행정사무감사': [('성과·집행','계획 대비 실적과 집행잔액의 사유는 무엇입니까?','성과자료·결산자료·집행잔액 산출내역'),('개선 요구','이전 요구사항은 어디까지 조치했습니까?','기존 회의록·조치계획·실적 증빙')],
 '예산심사': [('증감·산출','전년 대비 증감과 단가·물량 산출근거는 무엇입니까?','전년·당년 예산서·산출기초·견적'),('재원·지속성','재원별 부담과 향후 운영비는 얼마입니까?','국·시·구비 구분·교부조건·중기 운영비')],
 '결산심사': [('집행·이월','집행잔액·이월·반환금이 발생한 이유는 무엇입니까?','결산서·집행내역·이월조서·정산자료'),('효과','집행 규모와 실제 성과를 어떻게 설명할 수 있습니까?','성과보고서·대상자·실적 산정기준')],
 '조례심사': [('권한·중복','상위법 위임·소관사무·기존 조례와의 관계는 무엇입니까?','검토 기준일의 법령·현행 조례·법무 검토'),('집행 가능성','비용·시행 절차·담당부서 준비는 충분합니까?','비용추계·협의 결과·집행계획')],
 '구정질문': [('사실·현황','질문에서 제기한 현황은 현재 자료와 일치합니까?','질문 원문·현황자료·기준일'),('대안·일정','가능한 조치와 추가 검토사항은 무엇입니까?','대안별 조건·일정·관계부서 의견')],
 '5분자유발언': [('제안 취지','공개 발언에서 제안한 정책 내용은 무엇입니까?','발언 원문·기존 사업현황'),('검토·회신','반영 가능한 부분과 추가 확인사항은 무엇입니까?','소관 검토·재원·후속 협의자료')],
 '업무보고': [('현황·계획','현재 추진상황과 다음 단계는 무엇입니까?','업무계획·기준일 현재 추진자료'),('애로·보완','지연·변경 사유와 보완대책은 무엇입니까?','일정 변경내역·협의자료·대안')],
}
NOTE='실무 검토자료입니다. 원문 인용·담당자 제공자료·준비 제안을 구분하며 최종 제출은 담당자가 확인합니다.'


def text(value, name, maximum=200, required=True):
 if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):raise ValueError(f'{name}: 1~{maximum}자 문자열이 필요합니다.')
 return value.strip()


def date(value,name):
 try:return dt.date.fromisoformat(text(value,name,10))
 except ValueError:raise ValueError(f'{name}는 실제 YYYY-MM-DD 날짜여야 합니다.') from None


def rows(value,name,maximum=30):
 if not isinstance(value,list) or len(value)>maximum or any(not isinstance(x,dict) for x in value):raise ValueError(f'{name}는 객체 {maximum}개 이내 목록이어야 합니다.')
 if len(json.dumps(value,ensure_ascii=False))>100000:raise ValueError(f'{name} 입력이 너무 큽니다.')
 return value


def purpose(value):
 if value not in PURPOSES:raise ValueError('용도는 '+', '.join(PURPOSES)+' 중 하나입니다.')
 return value


def plan_session(department, topics, meeting_type='행정사무감사',meeting_date=None,council='광주 서구'):
 department=text(department,'department');purpose(meeting_type);council=text(council,'council')
 if not isinstance(topics,list) or not 1<=len(topics)<=10:raise ValueError('topics는 1~10개입니다.')
 topics=list(dict.fromkeys(text(x,'topic') for x in topics))
 day=date(meeting_date,'meeting_date') if meeting_date else None
 stages=[(-14,'근거 수집','과거 논의·답변·후속조치 후보 확인'),(-7,'자료 대조','현재 수치·예산·기준일·출처를 대조'),(-3,'내부 검토','부서장 검토 및 관계부서 사실 확인'),(-1,'최종 준비','답변카드와 제출자료의 수치·판본 일치 확인'),(1,'회의 후 정리','요구자료·후속조치·회신 경로를 원문과 대조')]
 schedule=[{'suggested_date':(day+dt.timedelta(days=n)).isoformat() if day else None,'relative_day':n,'stage':s,'task':t,'status':'담당자 확인 필요'} for n,s,t in stages]
 return {'status':'COMPLETE','workflow':'session_plan','council':council,'department':department,'meeting_type':meeting_type,
 'meeting_date':meeting_date,'schedule':schedule,'schedule_basis':'내부 준비용 제안 일정(달력일 기준). 법정 기한·기관 확정 일정이 아님.',
 'topic_tasks':[{'topic':t,'search':{'tool':'council_evidence_bundle','arguments':{'keyword':t,'council':council}},
 'checklist':[{'focus':a,'preparation_question':b,'documents':c} for a,b,c in PURPOSES[meeting_type]],
 'required_fields':['자료 기준일','금액 단위','회의연도/회계연도 구분','담당자 확인','근거 문서·쪽수'],'owner':None} for t in topics],
 'submission_checklist':['질문별 핵심 답변이 있는지','현재 수치와 과거 발언을 구분했는지','조건·확정 여부·담당부서를 확인했는지','검토되지 않은 조치를 확약하지 않았는지'],
 'limitations':[NOTE,'준비 질문은 특정 의원의 실제 질문이나 질문 확률을 예측한 것이 아닙니다.'],'stored':False}


def provided_facts(facts):
 result=[];ids=set()
 for i,f in enumerate(rows(facts,'facts')):
  ident=text(f.get('id',f'F{i+1}'),'fact.id',60)
  if ident in ids:raise ValueError('fact.id가 중복되었습니다.')
  ids.add(ident)
  claim=text(f.get('text'),'fact.text',3000)
  ref=text(f.get('document_ref',''),'document_ref',500,False)
  asof=f.get('as_of')
  if asof:date(asof,'as_of')
  fy=f.get('fiscal_year')
  if fy is not None and (type(fy)!=int or not 1900<=fy<=2200):raise ValueError('fiscal_year는 1900~2200 정수 또는 null입니다.')
  result.append({'id':ident,'text':claim,'document_ref':ref or None,'as_of':asof,
    'unit':text(f.get('unit',''),'unit',30,False) or None,'fiscal_year':fy,
    'source_kind':'USER_PROVIDED','verification':'제공자료·서버 미검증',
    'missing_fields':[k for k,v in [('document_ref',ref),('as_of',asof)] if not v]})
 return result


def select_events(payload,event_ids):
 if not isinstance(event_ids,list) or not 1<=len(event_ids)<=8 or any(not isinstance(x,str) for x in event_ids):raise ValueError('event_ids는 근거 식별자 1~8개입니다.')
 index={x.get('event_id'):x for x in payload.get('items',[])}
 if any(x not in index for x in event_ids):raise ValueError('이 근거 묶음에 없는 event_id입니다. council_get_evidence로 확인하세요.')
 return [copy.deepcopy(index[x]) for x in dict.fromkeys(event_ids)]


def brief_event(event):
 """Verbatim prefixes explicitly marked; retain usable origin reference, not invented IDs."""
 out={k:copy.deepcopy(event.get(k)) for k in ('event_id','record_id','docid','metadata','source_kind','provenance')}
 def quote(turn):
  if not turn:return None
  body=turn.get('text','');part=body[:1200];citation=copy.deepcopy(turn.get('citation') or {})
  return {'text':part,'label':turn.get('label'),'turn_index':turn.get('turn_index'),
   'citation':citation,'display_char_start':0,'display_char_end':len(part),'full_text_chars':len(body),
   'truncated':len(part)<len(body),'retrieval':{'tool':'council_read_source','arguments':{'ref':('site:' if event.get('provenance',{}).get('source')=='SEOGU_SITE' else '')+str(event.get('docid') or ''),'start_turn':turn.get('turn_index',0)}}}
 out['question']=quote(event.get('question'));out['speech']=quote(event.get('speech'))
 out['answers']=[quote(a) for a in event.get('answers',[])[:2]]
 out['answers_omitted_count']=max(0,len(event.get('answers',[]))-2)
 return out


def build_issue_card(payload,event_ids,topic,department,meeting_type,facts):
 text(topic,'topic');text(department,'department');purpose(meeting_type)
 events=select_events(payload,event_ids);facts=provided_facts(facts)
 return {'status':'PARTIAL','workflow':'issue_card','title':f'{topic} 의회 답변 준비카드','department':department,'meeting_type':meeting_type,
 'evidence':[brief_event(e) for e in events],'current_facts':facts,
 'answer_sections':[{'section':s,'draft':None,'instruction':v} for s,v in [
 ('질문·제안 요지','선택한 실제 발언에서 정책 쟁점만 정리'),('현재 현황','담당자가 확인한 기준일·수치·단위·자료를 기재'),
 ('핵심 답변','확인된 사실에 따라 가능·조건부 검토·추가확인으로 구분'),('근거·설명','과거 답변과 현재 자료의 변화 사유를 확인'),('후속조치','확정된 담당·내용·일정만 기재')]],
 'preparation_checks':[{'focus':a,'question':b,'documents':c} for a,b,c in PURPOSES[meeting_type]],
 'missing_documents':list(dict.fromkeys(k for f in facts for k in f['missing_fields'])) if facts else ['현재 현황자료','기준일','산출근거'],
 'ready_for_submission':False,'coverage':payload.get('coverage',[]),'source_status':payload.get('status'),
 'limitations':[NOTE,'현재 답변과 이행 여부를 과거 회의록만으로 확정하지 않습니다.'],'stored':False}


NUMBER=re.compile(r'(?<![\d.,])[+-]?\d[\d,]*(?:\.\d+)?\s*(?:조\s*원|억\s*원|백만\s*원|천\s*원|만\s*원|원|%|퍼센트|명|건|개소|회|년|월|일)')
def numbers(s):return [(m.group(0),m.start(),m.end()) for m in NUMBER.finditer(s)]
def norm(s):return re.sub(r'\s+','',s).replace(',','')


def review_answer(draft,facts,claims,official_events=None):
 text(draft,'draft',20000);facts=provided_facts(facts);rows(claims,'claims',40)
 index={f['id']:f for f in facts};checks=[];covered=[]
 for c in claims:
  statement=text(c.get('text'),'claim.text',3000);fid=c.get('fact_id');f=index.get(fid)
  start=c.get('start_char')
  if start is None:
   occurrences=[m.start() for m in re.finditer(re.escape(statement),draft)]
   start=occurrences[0] if len(occurrences)==1 else None
  located=type(start)==int and start>=0 and draft[start:start+len(statement)]==statement
  if located:covered.append((start,start+len(statement)))
  citation=text(c.get('support_excerpt',''),'support_excerpt',3000,False)
  exact=bool(f and citation and citation in f['text'])
  checks.append({'claim':statement,'start_char':start if located else None,'fact_id':fid,'located_in_draft':located,
   'support_excerpt':citation or None,'support_status':'제공자료 내 문구 일치·의미 일치 미판정' if exact else '제공자료 근거 연결 미확인',
   'issues':([ '초안 위치 미확인 또는 중복 문구: start_char 지정 필요'] if not located else [])+(['유효한 fact_id·원문 발췌 필요'] if not exact else [])})
 numeric=[]
 for token,a,b in numbers(draft):
  candidates=[f['id'] for f in facts if norm(token) in {norm(n[0]) for n in numbers(f['text'])}]
  numeric.append({'token':token,'start_char':a,'end_char':b,'candidate_fact_ids':candidates,
   'status':'같은 숫자·단위 표기 발견(의미·기준연도 미검증)' if candidates else '같은 숫자·단위 표기 미발견',
   'claim_linked':any(x<=a and b<=y for x,y in covered)})
 rules=[('확약 확인',r'(반드시|무조건|전액|전면|모두).{0,35}(하겠습니다|추진|지급|해결)','확정 근거·재원·권한·일정을 확인하고 조건을 명시'),
 ('설명 보완',r'(검토하겠습니다|노력하겠습니다|적극 추진하겠습니다)','무엇을 누가 언제까지 확인할지 구체화'),
 ('완료 근거',r'(완료하였|완료했|조치하였|조치했|해결되었|해결됐|이행하였)','조치 대상·일자·증빙자료·확인자를 명시'),
 ('표현 검토',r'(근거 없는 주장|터무니없|억지 주장|무지한|정치공세)','상대방 평가를 줄이고 사실관계·정책 근거로 설명')]
 issues=[{'category':cat,'excerpt':m.group(0),'start_char':m.start(),'advice':advice} for cat,regex,advice in rules for m in re.finditer(regex,draft)]
 # Always retain a candid manual review list; absence of flags is not approval.
 return {'status':'PARTIAL','workflow':'answer_review','claim_checks':checks,'numeric_checks':numeric,
 'expression_checks':issues,'missing_fact_metadata':[{'fact_id':f['id'],'missing':f['missing_fields']} for f in facts if f['missing_fields']],
 'historical_evidence':[brief_event(e) for e in (official_events or [])],
 'manual_review':['질문에 직접 답했는지','인용문 전후 맥락·조건·부정 표현이 유지되는지','같은 수치의 사업·연도·단위·분모가 일치하는지','법령·재원·권한의 현재 유효성을 확인했는지'],
 'ready_for_submission':False,'limitations':[NOTE,'숫자·문구 일치는 내용의 사실성 또는 해당 주장 입증을 의미하지 않습니다.','자동 문장 수정·법률 적합성 판정·완료 승인을 하지 않습니다.'],'stored':False}


def review_followups(payload,updates,as_of):
 day=date(as_of,'as_of');rows(updates,'updates',30)
 # Use exact server-generated commitment event IDs, never invented fulfillment claims.
 index={x.get('event_id'):x for x in payload.get('followup_items',[])};seen=set();items=[]
 for row in updates:
  ident=row.get('event_id')
  if ident not in index or ident in seen:raise ValueError('후속조치 event_id가 없거나 중복입니다.')
  seen.add(ident);event=index[ident];state=row.get('reported_status','미확인')
  if state not in ('미확인','검토중','추진중','완료보고','보류'):raise ValueError('reported_status는 미확인/검토중/추진중/완료보고/보류입니다.')
  due=row.get('due_date');due_day=date(due,'due_date') if due else None
  basis=text(row.get('due_basis',''),'due_basis',500,False)
  if due and not basis:raise ValueError('due_date는 담당자가 확정한 근거 due_basis와 함께 입력하세요.')
  support=row.get('evidence',[]);rows(support,'evidence',10)
  verified=[]
  for ev in support:
   ref=text(ev.get('document_ref',''),'document_ref',500,False)
   excerpt=text(ev.get('excerpt',''),'excerpt',3000,False)
   reviewer=text(ev.get('reviewer',''),'reviewer',100,False)
   checked=ev.get('checked_at');checked_day=date(checked,'checked_at') if checked else None
   if checked_day and checked_day>day:raise ValueError('증빙 확인일이 검토 기준일보다 늦습니다.')
   verified.append({'document_ref':ref or None,'excerpt':excerpt or None,'reviewer':reviewer or None,'checked_at':checked,
                    'fields_complete':bool(ref and excerpt and reviewer and checked),'source_kind':'USER_PROVIDED'})
  complete=bool(verified) and all(e['fields_complete'] for e in verified)
  flag='완료보고·증빙 확인요건 구비(내용 적합성 미검증)' if state=='완료보고' and complete else '완료보고·증빙 보완 필요' if state=='완료보고' else '담당자 보고 상태·독립 검증 전'
  items.append({'event_id':ident,'commitment':event.get('commitment'),'source':brief_event(event),'reported_status':state,
   'review_status':flag,'fulfillment_verified':False,'due_date':due,'due_basis':basis or None,
   'days_past_due':max(0,(day-due_day).days) if due_day else None,
   'attention':'기한 경과·조치상태 확인 필요' if due_day and due_day<day and state!='완료보고' else '완료보고 증빙 재확인' if state=='완료보고' else '기한·진행상태 확인',
   'evidence':verified,'owner_department':text(row.get('owner_department',''),'owner_department',100,False) or None})
 return {'status':'PARTIAL','workflow':'followup_review','as_of':as_of,'items':items,'reviewed_count':len(items),
  'unreviewed_candidate_count':len(index)-len(items),'limitations':[NOTE,'기한은 담당자 입력값이며 회의록의 상대 기한을 자동 환산하지 않습니다.','기한 경과는 미이행 판정이 아닙니다. 증빙 문서는 실제로 열람하지 않습니다.'],'stored':False}


def check_figures(data):
 from decimal import Decimal,InvalidOperation,ROUND_HALF_UP,localcontext
 rows(data,'data',30);items=[]
 def num(value,name):
  if isinstance(value,bool) or not isinstance(value,(str,int)):raise ValueError(f'{name}: 쉼표 없는 숫자 문자열 또는 정수 필요')
  try:d=Decimal(str(value))
  except InvalidOperation:raise ValueError(f'{name}: 숫자 형식 오류') from None
  if not d.is_finite() or abs(d)>Decimal('1e18') or d.as_tuple().exponent < -6:raise ValueError('숫자 범위 또는 소수자리 초과')
  return d
 def show(d):return format(d,'f')
 def pct(a,b):
  if not b:return None
  with localcontext() as ctx:
   ctx.prec=60
   return show((a/b*100).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
 for row in data:
  name=text(row.get('name'),'name');unit=text(row.get('unit'),'unit',30)
  out={'name':name,'unit':unit,'source_kind':'USER_PROVIDED','verification':'입력값 산술검사·원자료 미검증','warnings':[]}
  if 'current' in row and 'previous' in row:
   cur=num(row['current'],'current');prev=num(row['previous'],'previous')
   out.update(current=show(cur),previous=show(prev),change=show(cur-prev),change_rate_pct=pct(cur-prev,prev),
    fiscal_year=row.get('fiscal_year'),previous_year=row.get('previous_year'),current_basis=row.get('current_basis'),previous_basis=row.get('previous_basis'))
   if prev==0:out['warnings'].append('전년 값 0: 증감률 산출 불가')
   if prev<0:out['warnings'].append('음수 기준값: 산식 증감률의 의미 별도 해석 필요')
   if not all(row.get(k) for k in ('fiscal_year','previous_year','current_basis','previous_basis')):out['warnings'].append('비교 연도·본예산/최종예산 등 기준 확인 필요')
   if 'reported_change' in row:out['reported_change_matches']=num(row['reported_change'],'reported_change')==cur-prev
  if 'budget' in row and 'executed' in row:
   budget=num(row['budget'],'budget');executed=num(row['executed'],'executed')
   if budget<0 or executed<0:raise ValueError('budget·executed는 0 이상이어야 합니다.')
   out.update(budget=show(budget),executed=show(executed),unspent=show(budget-executed),execution_rate_pct=pct(executed,budget))
   if not budget:out['warnings'].append('예산 0: 집행률 산출 불가')
   if executed>budget:out['warnings'].append('입력 집행액이 예산액 초과: 단위·회계·기준 확인 필요')
  if 'change' not in out and 'unspent' not in out:raise ValueError('current+previous 또는 budget+executed 쌍이 필요합니다.')
  items.append(out)
 return {'status':'COMPLETE','workflow':'figure_check','items':items,'rounding':'비율 소수점 둘째 자리 반올림(ROUND_HALF_UP)',
 'limitations':['같은 행의 금액은 동일 단위라는 전제입니다. 단위 자동 환산·원자료 진위 확인·회계 적법성 판정을 하지 않습니다.'],'stored':False}
