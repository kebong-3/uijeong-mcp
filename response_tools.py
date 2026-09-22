"""Practical response tools: public evidence may persist; inputs never do."""
from __future__ import annotations
from typing import Any, Optional
import datetime as dt
import council_workbench as C
import response_core as Q
from result_contract import wire_result


def install(U,store):
    def register(fn,*,local=True):
        setattr(U,fn.__name__,fn)
        if U.profile_allows(fn.__name__):
            U.mcp.tool(name=fn.__name__,annotations=U.RO_LOCAL if local else U.RO)(wire_result(fn))
        return fn

    def invalid(error):return {'status':'INVALID_INPUT','message':str(error),'items':[]}

    def load_many(snapshot_ids):
        if not isinstance(snapshot_ids,list) or len(snapshot_ids)>4 or any(not isinstance(s,str) or not s or len(s)>128 for s in snapshot_ids):
            raise ValueError('snapshot_ids는 실제 검색으로 받은 식별자 최대 4개입니다.')
        out=[]
        for ident in dict.fromkeys(snapshot_ids):
            payload=store.get(ident)
            if not payload:raise ValueError('근거 묶음이 없거나 만료되었습니다. 다시 검색하세요.')
            out.append((ident,payload))
        return out

    @register
    async def council_audit_claims(draft:str,claims:list[dict[str,Any]],
        snapshot_ids:Optional[list[str]]=None,facts:Optional[list[dict[str,Any]]]=None,
        as_of:Optional[str]=None,max_age_days:int=180)->dict[str,Any]:
        """답변 문장별 원문 대조. 숫자가 없는 미연결 주장도 찾고 변형 인용·현재/과거 혼용을 표시.
        claims=[{text,kind:direct_quote|historical_summary|current_statement,citation_id,support_excerpt,start_char(선택)}].
        citation_id는 council_prepare_response 결과 citations의 E:... 또는 제공자료 F:<id>를 사용.
        facts=[{id,text,document_ref,as_of:'YYYY-MM-DD',unit,fiscal_year}]. snapshot_ids 최대4개.
        정확한 문자열·위치만 검증하고 의미적 입증·최종승인은 하지 않는다. 내부 입력 저장 없음.
        """
        try:return Q.audit_claims(draft,claims,load_many(snapshot_ids or []),facts or [],as_of,max_age_days)
        except (ValueError,TypeError) as exc:return invalid(exc)

    @register
    async def council_compare_metrics(data:list[dict[str,Any]])->dict[str,Any]:
        """비교 기준이 같은 예산·성과 수치만 계산(1~30행). 금액 단위 환산·%p·0분모 처리.
        data=[{name,mode:year_over_year|same_period,previous:{value,unit,fiscal_year,metric,entity,population,
        period_basis,accounting_basis,document_ref},current:{동일 필드}}].
        단위=원/천원/만원/백만원/억원/명/건/개/개소/%/회. value는 정수 또는 숫자 문자열.
        period_basis 예 연간/1~8월누적, accounting_basis 예 최종예산/본예산/실인원.
        필수 비교기준 누락·불일치 시 계산값을 비워 잘못된 비교를 차단. 제공자료 진위 검증 없음.
        """
        try:return Q.compare_metrics(data)
        except (ValueError,TypeError) as exc:return invalid(exc)

    @register
    async def council_compare_evidence(snapshot_ids:list[str],pairs:list[dict[str,Any]])->dict[str,Any]:
        """과거 답변·다른 회의 발언을 원문 그대로 나란히 대조한다.
        pairs=[{left:{citation_id,excerpt},right:{citation_id,excerpt}}], 1~12쌍.
        citation_id는 council_prepare_response의 citations에서 선택. snapshot_ids 최대4개.
        원문에 없는 발췌 거부, 숫자·조건·부정 표현 단서를 표시하되 모순·미이행을 확정하지 않는다.
        """
        try:return Q.compare_evidence(pairs,load_many(snapshot_ids))
        except (ValueError,TypeError) as exc:return invalid(exc)

    async def council_prepare_response(topic:str,department:str,date_from:str,date_to:str,
        council:str='광주 서구',meeting_type:str='행정사무감사',committee:Optional[str]=None,
        source:str='auto',max_docs:int=6,facts:Optional[list[dict[str,Any]]]=None,
        as_of:Optional[str]=None,snapshot_id:Optional[str]=None,event_offset:int=0,
        max_events:int=6,source_offset:int=0,site_start_page:int=1)->dict[str,Any]:
        """의회 답변 준비의 기본 진입. 기간별 검색→인용ID→과거질답·현황·준비질문·확인사항을 한 번에 작성.
        topic은 사업명·쟁점어, department는 작성부서(소관 확정 또는 부서 필터가 아님).
        date_from/date_to는 YYYY-MM-DD. source=auto|clik|site, max_docs=1~15(출처별).
        facts=[{id,text,document_ref,as_of,unit,fiscal_year}], 담당자 제공자료이며 서버 미검증.
        같은 조건+snapshot_id+event_offset으로 검색 재호출 없이 이어보기. next_actions는 남은 수집 경로.
        plain_text는 출처를 붙인 서구 보고서형 준비자료. 정책 판단·현재 답변을 지어내지 않는다.
        """
        try:
            # Validate private inputs BEFORE any public collection or storage.
            C.text(topic,'topic');C.text(department,'department');C.purpose(meeting_type)
            day=Q.review_day(as_of)
            start=C.date(date_from,'date_from');end=C.date(date_to,'date_to')
            if start>end or end>day:raise ValueError('검색기간은 시작일≤종료일≤검토 기준일이어야 합니다.')
            if (end-start).days>366*10:raise ValueError('한 번의 검색기간은 최대 10년입니다. 나누어 조회하세요.')
            Q.fact_records(facts or [],day.isoformat())
            if type(event_offset)!=int or event_offset<0 or type(max_events)!=int or not 1<=max_events<=8:
                raise ValueError('event_offset은 0 이상, max_events는 1~8 정수입니다.')
            bundle=await U.council_evidence_bundle(keyword=topic,council=council,committee=committee,
                date_from=date_from,date_to=date_to,source=source,max_docs=max_docs,snapshot_id=snapshot_id,
                limit=1,source_offset=source_offset,site_start_page=site_start_page)
            if bundle.get('status')=='INVALID_INPUT' or not bundle.get('snapshot_id'):return bundle
            sid=bundle['snapshot_id'];payload=load_many([sid])[0][1]
            result=Q.build_response(payload,sid,topic,department,meeting_type,facts or [],day.isoformat(),event_offset,max_events)
            public_args=dict(keyword=topic,council=council,committee=committee,date_from=date_from,
                date_to=date_to,max_docs=max_docs)
            actions=[]
            for cov in payload.get('coverage',[]):
                if cov.get('next_offset') is not None:
                    actions.append({'reason':'CLIK 미조회 목록','tool':'council_evidence_bundle',
                        'arguments':{**public_args,'source':'clik','source_offset':cov['next_offset']}})
                if cov.get('next_page') is not None and not cov.get('exhausted'):
                    actions.append({'reason':'서구의회 미조회 목록','tool':'council_evidence_bundle',
                        'arguments':{**public_args,'source':'site','site_start_page':cov['next_page']}})
                for ref in cov.get('pending_refs',[]):
                    actions.append({'reason':'목록에서 발견한 미열람 회의','tool':'council_read_source','arguments':{'ref':ref}})
            if result['next_event_offset'] is not None:
                actions.insert(0,{'reason':'같은 수집 결과의 다음 답변 준비 페이지','tool':'council_prepare_response',
                    'arguments':dict(topic=topic,department=department,date_from=date_from,date_to=date_to,council=council,
                        meeting_type=meeting_type,committee=committee,source=source,max_docs=max_docs,as_of=day.isoformat(),
                        snapshot_id=sid,event_offset=result['next_event_offset'],max_events=max_events,
                        source_offset=source_offset,site_start_page=site_start_page),
                    'private_input_note':'현황자료가 필요하면 동일 facts를 다시 전달하세요. 저장된 자료가 아닙니다.'})
            from response_guidance import supporting_sources
            result['supporting_document_routes']=supporting_sources(payload.get('parameters',{}).get('council'))
            result['next_actions']=actions
            result['recovery']={'tool':'council_prepare_response','arguments':dict(
                topic=topic,department=department,date_from=date_from,date_to=date_to,council=council,
                meeting_type=meeting_type,committee=committee,source=source,max_docs=max_docs,as_of=day.isoformat(),
                snapshot_id=sid,event_offset=event_offset,max_events=1,source_offset=source_offset,site_start_page=site_start_page),
                'note':'표시 축약 시 한 건씩 재호출. 현황자료 facts는 필요시 다시 전달.'}
            if bundle.get('warnings'):result['warnings']=bundle['warnings']
            return result
        except (ValueError,TypeError) as exc:return invalid(exc)
    register(council_prepare_response,local=False)
