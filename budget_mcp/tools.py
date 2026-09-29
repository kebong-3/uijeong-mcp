"""Explicit JSON Schemas and default-deny public capability registration."""
from .money import BudgetError

def S(desc='',**kw):return {'type':'string','maxLength':2000,'description':desc,**kw}
def I(minimum=0,maximum=100000,**kw):return {'type':'integer','minimum':minimum,'maximum':maximum,**kw}
def O(**kw):return {'type':'object','maxProperties':1000,**kw}
def B():return {'type':'boolean'}
def A(**kw):return {'type':'array','maxItems':100,**kw}
ID=S('budget_import/budget_datasets에서 반환된 정확한 dataset_id',pattern='^[a-f0-9]{24}$')
RID=S('계산 도구가 반환한 정확한 report_id',pattern='^[a-f0-9]{24}$')
UNIT=S(enum=['원','천원','백만원','억원'])
TOPIC=S(enum=['일반','보조금','시설','위탁','인건비','행사','기금'])
NUM={'type':['string','integer','null'],'description':'숫자 문자열 권장; 공란은 미확인. 부동소수 JSON 숫자는 허용하지 않음','maxLength':70}

def tool(name,method,desc,props=None,required=None,public=False,write=False,network=False):
    return {'name':'budget_'+name,'method':method,'public':public,'description':desc,
        'inputSchema':{'type':'object','properties':props or {},'required':required or [],'additionalProperties':False},
        'annotations':{'readOnlyHint':not write,'destructiveHint':name=='delete','idempotentHint':not write,'openWorldHint':network}}

TOOLS=[
 tool('status','status','독립형 지방예산 MCP의 버전·프로필·키 설정 여부. 연결 정상 여부는 별도.',public=True),
 tool('guide','guide','예산행정 업무흐름, 입력서식, 구현범위와 보안 주의사항.',public=True),
 tool('inspect_file','inspect_file','[로컬] inputs 내 CSV/XLSX 열제목·상위 5행을 확인. 파일내용이 AI 클라이언트로 전달됨.',
      {'file':S(),'sheet':S(),'header_row':I(1,100),'encoding':S(enum=['utf-8-sig','cp949'])},['file']),
 tool('import','import_file','[로컬/저장] 명시적 열매핑·연도·단계·단위와 함께 정형 예산파일 가져오기. 원본 변경 없음.',
      {'file':S(),'spec':O()},['file','spec'],write=True),
 tool('datasets','datasets','[로컬] 등록한 자료 목록·회계연도·편성단계 조회.'),
 tool('rows','rows','[로컬] 원본 행번호·파일해시를 가진 표준화 행을 페이지 단위 조회.',
      {'dataset_id':ID,'offset':I(),'limit':I(1,100)},['dataset_id']),
 tool('validate','validate','[로컬/결과저장] 총계·재원합계·집행·세입 산술 검산. 법적 판단 아님.',{'dataset_id':ID},['dataset_id'],write=True),
 tool('compare','compare','[로컬/결과저장] 같은 기관·세입세출·누계 기준 자료의 사업코드별 증감 및 차이 분해.',
      {'before_id':ID,'after_id':ID,'field':S(),'project_crosswalk':O(additionalProperties=S())},['before_id','after_id'],write=True),
 tool('funding','funding','[로컬/결과저장] 국고+균특+기금보조금과 시군구비/지방비전체를 구분. 부담액순은 정책평가 아님.',
      {'dataset_id':ID,'scope':S(enum=['시군구비','시도비+시군구비']),'national_only':B(),'limit':I(1,100)},['dataset_id'],write=True),
 tool('group','group','[로컬/결과저장] 부서·회계·통계목·사업코드별 합계. 통계목 접두어를 명시해 대상범위 선택; 분류기준 자동인증 아님.',
      {'dataset_id':ID,'by':A(items=S(enum=['department','account','budget_code','project_id'])),'fields':A(items=S()),'code_prefixes':A(items=S())},['dataset_id'],write=True),
 tool('execution','execution','[로컬/결과저장] 미집행액·미원인행위 추정·결산잔액 검산. 감액가능액 단정 금지.',{'dataset_id':ID},['dataset_id'],write=True),
 tool('revenue','revenue','[로컬/결과저장] 예산현액·징수결정·실제수납 차이 분해. 체납 등 원인 자동 추정 금지.',{'dataset_id':ID},['dataset_id'],write=True),
 tool('scenario','scenario','[로컬/결과저장] 사용자 지정 변동률의 단순 산술 시나리오. 자동 감액 추천 아님.',
      {'dataset_id':ID,'rates':O(additionalProperties=NUM),'reason':S()},['dataset_id','rates','reason'],write=True),
 tool('cost','cost','단가×물량×횟수×기간 계산. 단가 근거·가정 필수; 법정부담은 자동 포함하지 않음.',
      {'components':A(items=O(properties={'name':S(),'basis':S(),'unit_price':NUM,'quantity':NUM,'count':NUM,'periods':NUM},required=['name','basis','unit_price','quantity'],additionalProperties=False)),
       'unit':UNIT},['components'],public=True),
 tool('settlement','settlement','입력된 세입·세출·이월·반납액으로 잉여금 계산. 원자료 중복/당해기준 확인 필요.',
      {'receipts':NUM,'expenditures':NUM,'carryovers':NUM,'grant_returns':NUM,'unit':UNIT},['receipts','expenditures','carryovers','grant_returns'],public=True),
 tool('change','change','증감액·증감률 계산. 0원 기준·음수·공란은 별도 표시.',{'before':NUM,'after':NUM,'unit':UNIT},['before','after'],public=True),
 tool('review','review','[로컬/결과저장] 자료·계산·기준질문·최종확인의 네 규칙 기반 역할로 예산업무 검토 묶음 생성.',
      {'dataset_id':ID,'topic':TOPIC},['dataset_id'],write=True),
 tool('result','result','[로컬] 저장된 전체 계산결과 이어보기. section=excluded로 재원 불명확 등 제외항목 조회.',
      {'report_id':RID,'offset':I(),'limit':I(1,100),'section':S(enum=['items','excluded'])},['report_id']),
 tool('export','export','[로컬/파일생성] 저장된 전체 결과를 CSV/HTML/JSON으로 출력. 원본 변경 없음.',
      {'report_id':RID,'format':S(enum=['csv','html','json']),'unit':UNIT,'digits':I(0,6)},['report_id'],write=True),
 tool('delete','delete','[로컬/삭제] confirm=true일 때 데이터셋·연관 결과·연관 출력파일 삭제. 입력 원본 제외.',
      {'dataset_id':ID,'confirm':B()},['dataset_id','confirm'],write=True),
 tool('checklist','checklist','예산 업무유형별 사전절차 검토 질문. 법률상 의무·금액기준 확정 아님.',
      {'topic':TOPIC,'year':I(1990,2100)},['topic','year'],public=True),
 tool('basis_search','basis_search','[로컬] 검수자·유효기간·출처를 가진 사용자 근거목록에서 회계연도/기준일에 맞는 문구 검색.',
      {'file':S(),'query':S(),'as_of':S(),'year':I(1990,2100)},['file','query','as_of','year']),
 tool('sources','sources','공식 데이터·기준 출처와 연결 구현상태 안내.',public=True),
 tool('law_search','law','[외부공개조회] LAW_OC로 행정규칙·시행법령 목록 검색. 내부정보를 검색어로 보내지 마세요.',
      {'query':S(maxLength=200),'target':S(enum=['admrul','eflaw']),'page':I(1,1000),'display':I(1,50)},['query'],public=True,network=True),
 tool('lofin_query','lofin','[외부공개조회] 운영자가 검수·활성화한 지방재정365 서비스만 조회. 기본 제공 목록은 비어 있음.',
      {'service':S(),'params':O(additionalProperties={'type':['string','integer']})},['service','params'],public=True,network=True)
]

def validate_schema(value,schema,path='arguments',depth=0):
    """Validate the JSON Schema subset emitted by this server; fail closed."""
    import re
    if depth>12:raise BudgetError('입력 중첩 깊이 초과')
    types=schema.get('type',[]);types=[types] if isinstance(types,str) else types
    ok={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
        'integer':isinstance(value,int) and not isinstance(value,bool),'boolean':isinstance(value,bool),'null':value is None}
    if types and not any(ok.get(t,False) for t in types):raise BudgetError(path+'의 자료형 오류')
    if 'enum' in schema and value not in schema['enum']:raise BudgetError(path+'의 허용값 오류')
    if isinstance(value,str):
        if len(value)>schema.get('maxLength',2000):raise BudgetError(path+'의 길이 초과')
        if '\x00' in value:raise BudgetError('NUL 문자를 허용하지 않습니다.')
        if 'pattern' in schema and not re.fullmatch(schema['pattern'],value):raise BudgetError(path+' 형식 오류')
    if isinstance(value,int) and not isinstance(value,bool):
        if value<schema.get('minimum',-10**20) or value>schema.get('maximum',10**20):raise BudgetError(path+'의 숫자 범위 오류')
    if isinstance(value,dict):
        if len(value)>schema.get('maxProperties',1000):raise BudgetError(path+'의 항목 수 초과')
        if any(k not in value for k in schema.get('required',[])):raise BudgetError(path+'의 필수 입력 누락')
        props=schema.get('properties',{});additional=schema.get('additionalProperties',{})
        for k,v in value.items():
            if not isinstance(k,str) or len(k)>200:raise BudgetError('속성명 오류')
            if k not in props and additional is False:raise BudgetError('알 수 없는 입력속성: '+k)
            validate_schema(v,props.get(k,additional if isinstance(additional,dict) else {}),path+'.'+k,depth+1)
    elif isinstance(value,list):
        if len(value)>schema.get('maxItems',1000):raise BudgetError(path+'의 배열 크기 초과')
        for v in value:validate_schema(v,schema.get('items',{}),path+'[]',depth+1)

