"""Explicit schemas preserve client discoverability without exposing arbitrary calls."""
from copy import deepcopy
from .tools import TOOLS,S,I,O,B,A,NUM,UNIT,TOPIC,tool

PARAMS=O(additionalProperties={'type':['string','integer'],'maxLength':1000})
COMPONENTS=next(t for t in TOOLS if t['name']=='budget_cost')['inputSchema']['properties']['components']
ANNUAL=A(maxItems=30,items=O(properties={'year':I(1990,2130),'operating':NUM,'maintenance':NUM,'replacement':NUM,'revenue':NUM},
                          required=['year','operating','maintenance','replacement','revenue'],additionalProperties=False))
COMPARATORS=A(items=O(properties={
    'id':S(),'amount':NUM,'quantity':NUM,'money_unit':UNIT,'quantity_unit':S(),'fiscal_year':I(1990,2100),
    'amount_basis':S(enum=['예산액','예산현액','집행액','계약금액','산출가정']),'cost_scope':S(),'tax_basis':S(),'source':S()},
    required=['id','amount','quantity','quantity_unit','fiscal_year','amount_basis','cost_scope','tax_basis','source'],additionalProperties=False))

EXTRA_TOOLS=[
 tool('api_catalog','api_catalog','공식 API별 신청 링크·인증 환경변수·정확한 필수/허용 매개변수·실검증 상태. 외부조회 전 사용.',
      {'query':S(maxLength=100)},public=True),
 tool('api_status','api_status','API별 키 설정 여부와 이 인스턴스에서 실제 확인된 응답상태. 비밀값은 반환하지 않습니다.',public=True),
 tool('fetch_api','fetch_api','[공식 외부조회] 카탈로그 ID로 1페이지 조회. 키는 서버 환경변수만 사용. 표본·실패·빈결과 구분.',
      {'api_id':S(maxLength=100),'params':PARAMS,'page':I(1,10000),'page_size':I(1,100),'use_sample':B()},
      ['api_id','params'],public=True,network=True),
 tool('search_similar_projects','search_similar_projects','[공식 외부조회] 지방재정365 사업명 키워드 후보. 회계연도·집행기준일 필수. 전체 검색이나 적정성 판단 아님.',
      {'query':S(maxLength=120),'fiscal_year':I(2016,2100),'execution_date':S(pattern=r'^\d{8}$'),'local_gov_code':S(pattern=r'^\d{0,10}$'),
       'region_code':S(pattern=r'^\d{0,10}$'),'page':I(1,10000),'page_size':I(1,100),'use_sample':B()},
      ['query','fiscal_year','execution_date'],public=True,network=True),
 tool('matching_funds','matching_funds','명시한 국비·시도비·시군구비·기타 비율로 원 단위 분담액 검산. 합계100% 검증; 보조대상 판정 아님.',
      {'total':NUM,'ratios':O(properties={k:NUM for k in ['national','provincial','municipal','other']},
          required=['national','provincial','municipal','other'],additionalProperties=False),'basis':S(),'unit':UNIT},
      ['total','ratios','basis'],public=True),
 tool('lifecycle_cost','lifecycle_cost','신규사업 초기비+연도별 운영·유지·교체비-수입의 다년도 비용. 미기재 연도/공란 구분; 할인율은 사용자 가정.',
      {'initial_cost':NUM,'annual_rows':ANNUAL,'base_year':I(1990,2100),'basis':S(),'unit':UNIT,'discount_pct':NUM},
      ['initial_cost','annual_rows','base_year','basis'],public=True),
 tool('variance_drivers','variance_drivers','동일 범위에서 단가·수량·교차효과의 금액증감 항등식 검산. 실제 변경사유의 증명은 아님.',
      {'before_price':NUM,'before_quantity':NUM,'after_price':NUM,'after_quantity':NUM,'basis':S(),'unit':UNIT},
      ['before_price','before_quantity','after_price','after_quantity','basis'],public=True),
 tool('calculate_unit_cost','benchmark','같은 연도·사업량단위·금액기준·범위·세금조건끼리만 단가 비교. 3건 미만 참고분포 보류. 사례 출처 필수.',
      {'comparators':COMPARATORS,'target_quantity':NUM},['comparators'],public=True),
 tool('adjust_inflation','inflation_adjust','동일 통계지수 계열의 기준/비교지수로 금액 환산. CPI 일괄 자동적용 없음.',
      {'value':NUM,'base_index':NUM,'target_index':NUM,'index_series':S(),'base_period':S(),'target_period':S(),'source':S(),'unit':UNIT},
      ['value','base_index','target_index','index_series','base_period','target_period','source'],public=True),
 tool('execution_plan','execution_plan','입력한 월별 집행계획과 실적 차이. 누락월/미확인실적 보존; 균등집행을 가정하지 않음.',
      {'periods':A(maxItems=36,items=O(properties={'period':S(pattern=r'^20\d{2}-(0[1-9]|1[0-2])$'),'planned':NUM,'actual':NUM},
       required=['period','planned','actual'],additionalProperties=False)),'unit':UNIT},['periods'],public=True),
 tool('review_project','review_proposal','공개 가능한 신규사업 산출안을 자료·산출·근거·교차검토 네 역할로 검토. 회의 쟁점과 원장 해시·사업설명서 구조 반환.',
      {'title':S(maxLength=160),'year':I(1990,2100),'components':COMPONENTS,'topic':TOPIC,'unit':UNIT,
       'context':O(properties={k:S() for k in ['beneficiaries','delivery_period','service_level']},additionalProperties=False)},
      ['title','year','components'],public=True)
]


def available_tools(public):
    tools=deepcopy(TOOLS+EXTRA_TOOLS)
    for t in tools:
        if t['name']=='budget_status':t['description']='통합 지방예산 MCP 버전·공개/로컬 분리·API 키 구성·실연결 확인 구분.'
        if t['name']=='budget_lofin_query':t['description']='공식 카탈로그의 지방재정365 API 조회. API ID/변수는 budget_api_catalog에서 확인.'
    return [t for t in tools if not public or t['public']]

