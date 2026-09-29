"""Public/private capability boundary for a standalone local-budget server."""
import json,os,copy
from . import __version__,analytics
from .money import BudgetError,won,variance,display
from .ingest import load_dataset,safe_file,read_table,HEADERS_KO
from .storage import Store
from .basis import SOURCES,checklist,search_local_basis
from .connectors import PublicClient
from .agents import review
from .reports import export_report


def page_result(report,offset=0,limit=30,section='items'):
    if not isinstance(offset,int) or isinstance(offset,bool) or offset<0 or not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=100:
        raise BudgetError('페이지 범위 오류')
    if section not in ('items','excluded'):raise BudgetError('조회 section은 items/excluded')
    rows=report.get(section,[])
    result={k:v for k,v in report.items() if k not in ('items','excluded')}
    result['section']=section;result['total_items']=len(rows);result['offset']=offset
    result['items']=[];used=0
    for r in rows[offset:offset+limit]:
        item=copy.deepcopy(r)
        if 'sources' in item and len(item['sources'])>20:
            item['sources_total']=len(item['sources']);item['sources']=item['sources'][:20];item['sources_truncated']=True
        size=len(json.dumps(item,ensure_ascii=False))
        if used+size>300000:break
        result['items'].append(item);used+=size
    result['next_offset']=offset+len(result['items']) if offset+len(result['items'])<len(rows) else None
    result['page_only']=result['next_offset'] is not None or offset>0
    if not result['items'] and offset<len(rows):
        result['note']='한 항목의 크기가 출력한도를 초과합니다. budget_export로 전체 결과를 확인하세요.'
        result['next_offset']=None;result['output_truncated']=True
    return result

class BudgetService:
    def __init__(self,root=None,public=False,client=None):
        self.public=public
        self.store=None if public else Store(root or os.getenv('BUDGET_HOME','./budget-workspace'))
        self.client=client or PublicClient()
    def private(self):
        if self.public or self.store is None:raise BudgetError('공개형 서버는 로컬 자료 접근을 허용하지 않습니다.')
        return self.store
    def dataset(self,id):return self.private().get('datasets',id)
    def persist(self,obj):
        rid=self.private().put('reports',obj)
        return {'report_id':rid,**page_result(obj,limit=obj.get('default_page_size',30))}
    def status(self):
        return {'server':'jibang-budget-mcp','version':__version__,'independent':True,
                'depends_on_council_mcp':False,'profile':'public' if self.public else 'private-local',
                'data_formats':['flat CSV','literal flat XLSX'],
                'financial_arithmetic':'integer KRW / Decimal; unknown is not zero',
                'external_AI_key_required':False,'external_api_keys':{
                    'LAW_OC':bool(os.getenv('LAW_OC')),'LOFIN_API_KEY':bool(os.getenv('LOFIN_API_KEY'))},
                'operational_note':'외부키 존재 표시는 연결성 검증을 뜻하지 않습니다.',
                'private_dataset_access':not self.public}
    def guide(self):
        return {'purpose':'공무원 지방예산 편성·집행·결산 실무 지원. 지방의회 MCP 하위모듈 아님.',
            'workflow':['budget_inspect_file','명시적 열 매핑 및 자료단위/연도/단계 확인','budget_import',
                        'budget_validate','budget_compare / budget_funding / budget_execution / budget_revenue',
                        'budget_review','budget_export'],
            'standard_fields':HEADERS_KO,
            'limits':['PDF/HWP/HWPX 자동표 추출 미구현','공식 재정시스템 쓰기/계좌/지출결의 접근 없음',
                      '공개 API가 내부 예산현황을 대체하지 않음','적법·부적법 자동확정이나 사업 우선순위 평가 없음'],
            'privacy':'로컬 서버라도 AI 클라이언트에 반환하는 발췌·수치는 AI 서비스로 전송될 수 있습니다. 기관 보안기준을 먼저 확인하세요.'}
    def inspect_file(self,file,sheet='데이터',header_row=1,encoding='utf-8-sig'):
        path=safe_file(self.private().inputs,file)
        records,digest=read_table(path,sheet,encoding)
        if not isinstance(header_row,int) or not 1<=header_row<=100:raise BudgetError('머리글 행 오류')
        headers=next((r for n,r in records if n==header_row),None)
        return {'file':path.name,'sha256':digest,'sheet':sheet,'headers':headers,
                'preview':[{'row':n,'cells':v} for n,v in records if n>header_row][:5],
                'physical_nonempty_rows':len(records),'automatic_mapping_applied':False}
    def import_file(self,file,spec):
        path=safe_file(self.private().inputs,file)
        ds=load_dataset(path,spec)
        self.private().put('datasets',ds,ds['dataset_id'])
        return {'dataset_id':ds['dataset_id'],'meta':ds['meta'],'row_count':len(ds['rows']),
                'sha256':ds['file_sha256'],'warnings':ds['warnings'],'source_overwritten':False}
    def datasets(self):return {'items':self.private().list()}
    def rows(self,dataset_id,offset=0,limit=30):
        ds=self.dataset(dataset_id)
        return page_result({'dataset_id':dataset_id,'meta':ds['meta'],'items':ds['rows']},offset,limit)
    def validate(self,dataset_id):return self.persist(analytics.validate(self.dataset(dataset_id)))
    def compare(self,before_id,after_id,field='budget_amount',project_crosswalk=None):
        return self.persist(analytics.compare(self.dataset(before_id),self.dataset(after_id),field,project_crosswalk))
    def funding(self,dataset_id,scope='시군구비',national_only=True,limit=10):
        return self.persist(analytics.funding(self.dataset(dataset_id),scope,national_only,limit))
    def group(self,dataset_id,by=None,fields=None,code_prefixes=None):return self.persist(analytics.group(self.dataset(dataset_id),by,fields,code_prefixes))
    def execution(self,dataset_id):return self.persist(analytics.execution(self.dataset(dataset_id)))
    def revenue(self,dataset_id):return self.persist(analytics.revenue(self.dataset(dataset_id)))
    def scenario(self,dataset_id,rates,reason):return self.persist(analytics.scenario(self.dataset(dataset_id),rates,reason))
    def cost(self,components,unit='원'):return analytics.estimate_cost(components,unit)
    def settlement(self,receipts,expenditures,carryovers,grant_returns,unit='원'):
        return analytics.settlement(receipts,expenditures,carryovers,grant_returns,unit)
    def change(self,before,after,unit='원'):
        return {'unit':'원','input_unit':unit,**variance(won(before,unit),won(after,unit))}
    def review(self,dataset_id,topic='일반'):return self.persist(review(self.dataset(dataset_id),topic))
    def result(self,report_id,offset=0,limit=30,section='items'):
        return {'report_id':report_id,**page_result(self.private().get('reports',report_id),offset,limit,section)}
    def export(self,report_id,format='html',unit='백만원',digits=0):return export_report(self.private(),report_id,format,unit,digits)
    def delete(self,dataset_id,confirm=False):return self.private().delete(dataset_id,confirm)
    def checklist(self,topic,year):return checklist(topic,year)
    def basis_search(self,file,query,as_of,year):return search_local_basis(self.private().inputs,file,query,as_of,year)
    def sources(self):return {'items':SOURCES,'note':'연계 후보와 구현 상태를 구분합니다. 서비스 가입/정상호출이 완료됐다는 뜻이 아닙니다.'}
    def law(self,query,target='admrul',page=1,display=10):return self.client.law_search(query,target,page,display)
    def lofin(self,service,params):return self.client.lofin_query(service,params,os.getenv('LOFIN_CATALOG_FILE'))

