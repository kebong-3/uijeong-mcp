"""Register practice tools with no network calls or private-data persistence."""
from __future__ import annotations
from typing import Any,Optional
import council_workbench as C
import dept_core as D
from result_contract import wire_result


def install(U,store):
 def register(fn):
  setattr(U,fn.__name__,fn)
  if U.profile_allows(fn.__name__):U.mcp.tool(name=fn.__name__,annotations=U.RO_LOCAL)(wire_result(fn))
  return fn
 def invalid(e):return {'status':'INVALID_INPUT','message':str(e),'items':[]}
 def fetch(ident):
  payload=store.get(ident)
  if not payload:raise ValueError('근거 묶음이 없거나 만료되었습니다. 다시 검색하세요.')
  return payload

 @register
 async def council_plan_session(department:str,topics:list[str],meeting_type:str='행정사무감사',meeting_date:Optional[str]=None,council:str='광주 서구')->dict[str,Any]:
  """회기 전 준비표. topics 1~10개, 용도=행정사무감사/예산심사/결산심사/조례심사/구정질문/5분자유발언/업무보고.
  council은 시·도와 시·군·구를 함께 지정한다(기본 광주 서구). 제안 일정과 준비질문·필요자료를 만든다. 법정 기한 또는 실제 의원 질문을 예측하지 않는다. 입력은 저장하지 않는다."""
  try:return C.plan_session(department,topics,meeting_type,meeting_date,council)
  except ValueError as e:return invalid(e)

 @register
 async def council_get_evidence(snapshot_id:str,collection:str='items',item_offset:int=0,limit:int=5)->dict[str,Any]:
  """검색 결과의 snapshot_id만으로 원래 근거를 이어보기. collection=items 또는 followup_items.
  후속조치 검토에 쓸 event_id를 얻는다. 실제 저장 결과를 재사용하며 외부 API를 호출하지 않는다."""
  try:
   if collection not in ('items','followup_items') or type(item_offset)!=int or item_offset<0 or type(limit)!=int or not 1<=limit<=20:raise ValueError('collection/offset/limit 범위 오류')
   payload=fetch(snapshot_id);items=payload.get(collection,[])
   if item_offset>len(items):raise ValueError('item_offset이 근거 수보다 큽니다.')
   next_pos=item_offset+limit if item_offset+limit<len(items) else None
   return {'status':'PARTIAL' if next_pos is not None else payload['status'],'snapshot_id':snapshot_id,
    'collection':collection,'item_offset':item_offset,'items':items[item_offset:item_offset+limit],'total_items':len(items),
    'next_item_offset':next_pos,'parameters':payload.get('parameters'),'coverage':payload.get('coverage'),
    'errors':payload.get('errors',[]),'limitations':payload.get('limitations',[])}
  except ValueError as e:return invalid(e)

 @register
 async def council_build_issue_card(snapshot_id:str,event_ids:list[str],topic:str,department:str,
         meeting_type:str='행정사무감사',facts:Optional[list[dict[str,Any]]]=None)->dict[str,Any]:
  """실제 검색 근거(event_id 1~8개)에 현재 자료를 붙여 쟁점별 답변카드를 만든다.
  facts=[{id,text,document_ref,as_of:'YYYY-MM-DD',unit,fiscal_year}]. facts는 담당자 제공자료로 표시하며 공식검증으로 승격하지 않는다.
  자동 답변 확정 없이 확인된 원문과 빈 답변 작성칸·누락자료를 제공한다. 비공개 입력은 저장하지 않는다."""
  try:return C.build_issue_card(fetch(snapshot_id),event_ids,topic,department,meeting_type,facts or [])
  except ValueError as e:return invalid(e)

 @register
 async def council_review_answer(draft:str,facts:Optional[list[dict[str,Any]]]=None,
         claims:Optional[list[dict[str,Any]]]=None,snapshot_id:Optional[str]=None,
         event_ids:Optional[list[str]]=None)->dict[str,Any]:
  """답변 초안의 숫자·단위·근거 연결·확약·설명 부족 표현을 점검한다(승인·법률판정 아님).
  facts=[{id,text,document_ref,as_of,unit,fiscal_year}]. claims=[{text,fact_id,support_excerpt,start_char(선택)}].
  같은 숫자가 발견돼도 사업·연도·분모가 같다는 뜻이 아니다. 원문 자동변경 없음. 입력 저장·외부 전송 없음."""
  try:
   if bool(snapshot_id)!=bool(event_ids):raise ValueError('과거 근거 사용 시 snapshot_id와 event_ids를 함께 입력하세요.')
   historical=C.select_events(fetch(snapshot_id),event_ids) if snapshot_id else []
   return C.review_answer(draft,facts or [],claims or [],historical)
  except ValueError as e:return invalid(e)

 @register
 async def council_review_followups(snapshot_id:str,updates:list[dict[str,Any]],as_of:str)->dict[str,Any]:
  """회의 후 후속조치 증빙 확인표. get_evidence(collection='followup_items')의 event_id로 연결한다.
  updates=[{event_id,reported_status:미확인/검토중/추진중/완료보고/보류,owner_department,due_date,due_basis,
  evidence:[{document_ref,excerpt,reviewer,checked_at}]}]. as_of=YYYY-MM-DD.
  완료보고와 증빙 구비를 구분하며 실제 이행완료를 자동 판정하지 않는다. 입력 저장 없음."""
  try:return C.review_followups(fetch(snapshot_id),updates,as_of)
  except ValueError as e:return invalid(e)

 @register
 async def council_check_figures(data:list[dict[str,Any]])->dict[str,Any]:
  """답변자료의 증감액·증감률·집행잔액·집행률 산술검사(최대30행).
  data=[{name,unit,current,previous,reported_change(선택),fiscal_year,previous_year,current_basis,previous_basis,
  budget(선택),executed(선택)}]. 금액은 쉼표 없는 숫자 문자열 또는 정수. 동일 행 동일 단위.
  현재와 전년 또는 예산과 집행액 쌍 필요. 0 기준 비율은 null; 원자료 검증·법률판정 없음."""
  try:return C.check_figures(data)
  except ValueError as e:return invalid(e)

 @register
 async def council_format_worksheet(form:str,topic:str,department:str,council:str='광주 서구',
   snapshot_id:Optional[str]=None,event_ids:Optional[list[str]]=None,
   facts:Optional[list[dict[str,Any]]]=None,prepared_on:Optional[str]=None)->dict[str,Any]:
  """확인된 근거와 제공자료를 기관 회의자료 서식 칸에 배치하고 붙여넣을 본문(plain_text)을 만든다.
  form=5분자유발언_회의자료/구정질문_답변서/행정사무감사_답변카드/1페이지_검토보고.
  snapshot_id+event_ids를 주면 실제 발언을 개요·질의요지 칸에, facts는 현황 칸에 넣는다.
  검토의견·답변요지처럼 판단이 필요한 칸은 비운 채 담당자 확인 대상으로 남기며 문장을 만들어 넣지 않는다.
  두 글자 항목명은 네 글자 폭으로 벌려 표기한다. 기관마다 서식이 다르므로 제출 전 소속 양식과 대조한다."""
  try:
   evidence=[];commitments=[]
   if snapshot_id:
    payload=fetch(snapshot_id)
    wanted=set(event_ids or [])
    chosen=[e for e in payload.get('items',[]) if not wanted or e.get('event_id') in wanted]
    if wanted and not chosen:raise ValueError('event_id가 이 근거 묶음에 없습니다. council_get_evidence로 확인하세요.')
    evidence=D.classify_department_events(chosen,department)
    evidence=evidence['answered']+evidence['unanswered']+evidence['other_mention'] or [
     {'metadata':e.get('metadata'),'docid':e.get('docid'),'event_id':e.get('event_id'),
      'question':{'speaker':(e.get('question') or {}).get('speaker'),
                  'text':(e.get('question') or {}).get('text')} if e.get('question') else None}
     for e in chosen]
    commitments=D.department_commitments(payload.get('followup_items',[]),department)
   return D.build_worksheet(form,topic=topic,department=department,council=council,
                            evidence=evidence,facts=facts or [],commitments=commitments,
                            prepared_on=prepared_on)
  except ValueError as e:return invalid(e)
