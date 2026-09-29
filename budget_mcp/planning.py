"""Budget planning calculations. No legal approval or policy ranking.

Numbers remain Decimal/integer KRW. Every projection is an explicit assumption.
This module performs no network requests or persistence.
"""
from __future__ import annotations
import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, localcontext
from .money import BudgetError, dec, won, exact_sum, pct
from .analytics import estimate_cost
from .basis import checklist


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def number(value, *, positive=False):
    if isinstance(value,float):
        raise BudgetError('소수는 JSON 실수가 아닌 문자열로 입력하세요.')
    value=dec(value)
    if value<0 or (positive and value==0):
        raise BudgetError('수치의 양수/비음수 조건을 확인하세요.')
    return value


def amount(value,unit='원',*,nullable=False):
    if isinstance(value,float):
        raise BudgetError('금액 소수는 문자열로 입력하세요.')
    value=won(value,unit)
    if value is None:
        if nullable:return None
        raise BudgetError('미확인 금액을 0으로 가정하지 않습니다.')
    if value<0:raise BudgetError('금액은 0 이상으로 입력하세요.')
    return value


def rounded(value):
    if abs(value)>10**16:raise BudgetError('계산금액 한도 초과')
    return int(value.quantize(Decimal(1),rounding=ROUND_HALF_UP))


def require_text(value,name):
    if not isinstance(value,str) or not value.strip() or len(value)>2000:
        raise BudgetError(name+'를 명시하세요.')
    return value.strip()


def rows_limit(rows,minimum=1,maximum=100):
    if not isinstance(rows,list) or not minimum<=len(rows)<=maximum:
        raise BudgetError(f'입력행은 {minimum}~{maximum}개여야 합니다.')


def matching_funds(total,ratios,basis,unit='원'):
    """Largest-remainder rounding conserves total, without deciding eligibility."""
    total=amount(total,unit);require_text(basis,'분담률 출처/가정')
    keys=('national','provincial','municipal','other')
    if not isinstance(ratios,dict) or set(ratios)!=set(keys):
        raise BudgetError('national/provincial/municipal/other 네 분담률을 모두 명시하세요.')
    rates={k:number(ratios[k]) for k in keys}
    with localcontext() as ctx:
        ctx.prec=100
        if sum(rates.values())!=100:raise BudgetError('재원분담률 합계는 정확히 100%여야 합니다.')
    with localcontext() as ctx:
        ctx.prec=60
        raw={k:Decimal(total)*rates[k]/100 for k in keys}
        allocation={k:int(raw[k].to_integral_value(rounding=ROUND_FLOOR)) for k in keys}
        remainder=total-sum(allocation.values())
        order=sorted(keys,key=lambda k:(-(raw[k]-allocation[k]),keys.index(k)))
        for k in order[:remainder]:allocation[k]+=1
    return {'status':'CALCULATED','unit':'원','total_won':total,'ratios_pct':{k:str(v) for k,v in rates.items()},
        'allocation_won':allocation,'reconciliation_difference_won':total-sum(allocation.values()),
        'rounding':'원 미만 내림 후 소수잔여 큰 재원부터 1원 배분; 동률은 입력 표준순서',
        'basis':basis,'eligibility_verified':False,'note':'가정한 분담률 계산이며 보조대상·교부가능성 확정이 아닙니다.'}


def lifecycle_cost(initial_cost,annual_rows,base_year,basis,unit='원',discount_pct='0'):
    rows_limit(annual_rows,1,30);require_text(basis,'사업기간·비용 가정')
    if not isinstance(base_year,int) or isinstance(base_year,bool) or not 1990<=base_year<=2100:
        raise BudgetError('기준연도 오류')
    initial=amount(initial_cost,unit)
    discount=number(discount_pct)
    if discount>100:raise BudgetError('할인율은 0~100% 사용자 가정으로 명시하세요.')
    years=[r.get('year') for r in annual_rows]
    if any(not isinstance(y,int) or isinstance(y,bool) or y<base_year or y>base_year+30 for y in years) or len(set(years))!=len(years):
        raise BudgetError('연도 중복 또는 30년 이내 기간 오류')
    items=[]
    with localcontext() as ctx:
        ctx.prec=60
        for row in sorted(annual_rows,key=lambda r:r['year']):
            vals={k:amount(row.get(k),unit,nullable=True) for k in ('operating','maintenance','replacement','revenue')}
            known=all(v is not None for v in vals.values())
            gross=sum(vals[k] for k in ('operating','maintenance','replacement')) if all(vals[k] is not None for k in ('operating','maintenance','replacement')) else None
            net=gross-vals['revenue'] if known else None
            pv=None if net is None else rounded(Decimal(net)/(1+discount/100)**(row['year']-base_year))
            items.append({'year':row['year'],**{k+'_won':v for k,v in vals.items()},'gross_cost_won':gross,'net_cost_won':net,'present_value_won':pv})
    missing_years=sorted(set(range(base_year,max(years)+1))-set(years))
    net_sum=exact_sum([initial]+[r['net_cost_won'] for r in items])
    present_sum=exact_sum([initial]+[r['present_value_won'] for r in items])
    return {'status':'PARTIAL' if missing_years or net_sum['missing_count'] else 'CALCULATED','unit':'원','initial_cost_won':initial,
        'base_year':base_year,'horizon_end':max(years),'missing_years':missing_years,'annual_rows':items,
        'included_years_net_total':net_sum,'included_years_present_total':present_sum,
        'full_horizon_net_cost_won':None if missing_years else net_sum['value_won'],
        'discount_pct':str(discount),'basis':basis,'note':'미기재 연도/비용은 0이 아닙니다. 보조금 종료 후 지방비·안전관리·철거비는 입력한 경우에만 반영합니다.'}


def variance_drivers(before_price,before_quantity,after_price,after_quantity,basis,unit='원'):
    require_text(basis,'동일 규격·범위 및 수량 가정')
    p0,p1=Decimal(amount(before_price,unit)),Decimal(amount(after_price,unit))
    q0,q1=number(before_quantity),number(after_quantity)
    with localcontext() as ctx:
        ctx.prec=60
        b,a=p0*q0,p1*q1
        components={'price':(p1-p0)*q0,'quantity':p0*(q1-q0),'interaction':(p1-p0)*(q1-q0)}
        if any(v!=v.to_integral_value() for v in [b,a,*components.values()]):
            raise BudgetError('원 미만 분해값입니다. 단가·수량의 정밀도를 조정하세요.')
        if any(abs(v)>10**16 for v in [b,a,*components.values()]):raise BudgetError('금액 한도 초과')
    return {'status':'CALCULATED','unit':'원','before_won':int(b),'after_won':int(a),'delta_won':int(a-b),
        'components_won':{k:int(v) for k,v in components.items()},'reconciliation_difference_won':int(a-b-sum(components.values())),
        'formula':'총증감=(신단가-구단가)×구수량+구단가×(신수량-구수량)+(신단가-구단가)×(신수량-구수량)',
        'basis':basis,'note':'산술 분해이며 실제 물가·사업변경 원인의 증명이 아닙니다.'}


def quantile(values,p):
    values=sorted(values);position=Decimal(len(values)-1)*p
    lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def benchmark(comparators,target_quantity=None):
    rows_limit(comparators,1,100)
    seen=set();groups={};excluded=[]
    dimensions=('quantity_unit','fiscal_year','amount_basis','cost_scope','tax_basis')
    allowed_basis={'예산액','예산현액','집행액','계약금액','산출가정'}
    for r in comparators:
        ident=require_text(r.get('id'),'사례 ID')
        if ident in seen:raise BudgetError('중복 사례 ID: '+ident)
        seen.add(ident)
        if r.get('amount_basis') not in allowed_basis:raise BudgetError('금액 기준을 명시하세요.')
        if any(r.get(k) in (None,'') for k in dimensions) or not r.get('source'):
            excluded.append({'id':ident,'reason':'비교기준 또는 원문 출처 누락'});continue
        cost=amount(r.get('amount'),r.get('money_unit','원'),nullable=True)
        if isinstance(r.get('quantity'),float):raise BudgetError('소수 사업량은 문자열로 입력하세요.')
        qty=dec(r.get('quantity'),required=False)
        if cost is None or qty is None or qty<=0:
            excluded.append({'id':ident,'reason':'금액/양의 사업량 미확인'});continue
        key=tuple(str(r[k]) for k in dimensions)
        with localcontext() as ctx:
            ctx.prec=60
            value=Decimal(cost)/qty
            if value>10**16:raise BudgetError('단가 허용범위 초과')
        groups.setdefault(key,[]).append({'id':ident,'amount_won':cost,'quantity':str(qty),
            'unit_cost_won':format(value.quantize(Decimal('.0001'),rounding=ROUND_HALF_UP),'f'),'source':r['source'],'value':value})
    out=[]
    target=None if target_quantity is None else number(target_quantity,positive=True)
    for key,items in groups.items():
        values=[r.pop('value') for r in items]
        reference=None
        if len(values)>=3:
            with localcontext() as ctx:
                ctx.prec=60
                vals={k:quantile(values,p) for k,p in [('p25',Decimal('.25')),('median',Decimal('.5')),('p75',Decimal('.75'))]}
                reference={k:format(v.quantize(Decimal('.01'),rounding=ROUND_HALF_UP),'f') for k,v in vals.items()}
                if target is not None:reference['target_scenario_won']={k:rounded(v*target) for k,v in vals.items()}
        out.append({'cohort':dict(zip(dimensions,key)),'count':len(items),'items':items,'reference_distribution':reference,
            'limitations':['명시된 연도·단위·금액기준·범위·세금조건이 같은 입력끼리만 묶었습니다. 실제 규격 동등성은 사람이 확인해야 합니다.']+(['3건 미만: 참고분포 산출 보류'] if len(items)<3 else [])})
    return {'status':'PARTIAL' if excluded else 'CALCULATED','cohorts':out,'excluded':excluded,
        'note':'검색순서·단가분포는 정책 우열·적정예산·감액 권고가 아닙니다. 인구는 실제 수혜인원을 대신하지 않습니다.'}


def inflation_adjust(value,base_index,target_index,index_series,base_period,target_period,source,unit='원'):
    cost=amount(value,unit);bi=number(base_index,positive=True);ti=number(target_index,positive=True)
    for v,n in [(index_series,'같은 지수 계열/기준년'),(base_period,'기준기간'),(target_period,'비교기간'),(source,'통계출처')]:require_text(v,n)
    with localcontext() as ctx:
        ctx.prec=60;adjusted=rounded(Decimal(cost)*ti/bi)
    return {'status':'CALCULATED','original_won':cost,'adjusted_reference_won':adjusted,
        'formula':'원금액 × 비교기간지수 ÷ 기준기간지수','index_series':index_series,'base_period':base_period,'target_period':target_period,
        'source':source,'note':'사용자가 선택한 동일계열 지수 환산입니다. CPI를 모든 공사·용역에 자동 적용하지 않습니다.'}


def execution_plan(periods,unit='원'):
    rows_limit(periods,1,36);seen=set();items=[];cumulative_planned=0;cumulative_actual=0;known=True
    for r in sorted(periods,key=lambda x:x.get('period','')):
        period=r.get('period','')
        if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',period) or period in seen:raise BudgetError('월 중복/형식 오류')
        seen.add(period)
        plan=amount(r.get('planned'),unit,nullable=True);actual=amount(r.get('actual'),unit,nullable=True)
        known=known and plan is not None and actual is not None
        cumulative_planned+=plan or 0;cumulative_actual+=actual or 0
        items.append({'period':period,'planned_won':plan,'actual_won':actual,'actual_minus_plan_won':None if plan is None or actual is None else actual-plan,
            'plan_fulfilment_pct':pct(actual,plan),'included_periods_cumulative_actual_won':cumulative_actual if known else None,
            'included_periods_cumulative_planned_won':cumulative_planned if known else None})
    indices=[int(p[:4])*12+int(p[5:]) for p in seen]
    gaps=max(indices)-min(indices)+1-len(indices)
    return {'status':'PARTIAL' if not known or gaps else 'CALCULATED','items':items,'missing_month_count':gaps,
        'note':'입력된 월별 계획과 비교합니다. 연말 집중집행·계약시기를 추정하거나 낮은 집행률을 비효율로 판정하지 않습니다.'}


class ScopeAgent:
    def run(self,project):
        return {'agent':'A1_자료범위','fiscal_year':project['year'],'source_state':'USER_PROVIDED_ASSUMPTIONS',
            'privacy':'공개 가능한 산출자료만 입력. 비공개 자료는 승인된 로컬 환경에서 처리.',
            'input_hash':digest(project),'scope_missing':[k for k in ('beneficiaries','delivery_period','service_level') if not project.get('context',{}).get(k)]}

class BudgetAgent:
    def run(self,project):
        result=estimate_cost(project['components'],project.get('unit','원'))
        return {'agent':'A2_예산산출','ledger':result,'ledger_hash':digest(result),
            'challenge':'입력에 없는 보험료·세금·유지비는 총액에 포함되었다고 해석할 수 없습니다.'}

class EvidenceAgent:
    def run(self,project):
        basis=checklist(project.get('topic','일반'),project['year'])
        return {'agent':'A3_근거절차','checklist':basis,'legal_eligibility':'NOT_DETERMINED',
            'challenge':'산출액이 계산되었다는 사실은 편성가능·보조대상·사전절차 완료의 증거가 아닙니다.'}

class CrossReviewAgent:
    def run(self,project,scope,calc,evidence):
        ledger=calc['ledger'];recomputed=sum(row['amount_won'] for row in ledger['items'])
        same=recomputed==ledger['summary']['total_won'] and digest(ledger)==calc['ledger_hash']
        if not same:raise BudgetError('교차검산 불일치: 결과 작성 중단')
        meeting=[
            {'from':'A1_자료범위','to':'A2_예산산출','issue':'사업대상·기간·서비스 수준이 비교에 충분한가?',
             'response':'명시적 누락을 유지하고 입력 산식만 계산','unresolved':scope['scope_missing']},
            {'from':'A2_예산산출','to':'A3_근거절차','issue':'산출내역의 적용단가와 과목 근거가 확보되었는가?',
             'response':'입력 basis는 가정이며 공식 승인으로 승격하지 않음','unresolved':['당해연도 지침·조문·별표 대조']},
            {'from':'A3_근거절차','to':'A4_교차검토','issue':'총액·법적판단·미확인 사항을 섞지 않았는가?',
             'response':'총액 재계산과 해시 일치 확인; 적법성·정책우선순위 판단은 보류','unresolved':['담당부서 확인','기관 보안기준 확인']}]
        return {'agent':'A4_교차검토','arithmetic_reconciled':same,'meeting':meeting,'conclusion':'REVIEW_REQUIRED',
            'human_decisions':['예산과목 확정','단가·규격 검수','법령·조례 및 사전절차 확인']}


def review_proposal(title,year,components,topic='일반',unit='원',context=None):
    require_text(title,'사업명')
    if not isinstance(year,int) or not 1990<=year<=2100:raise BudgetError('회계연도 오류')
    project={'title':title,'year':year,'components':components,'topic':topic,'unit':unit,'context':context or {}}
    scope=ScopeAgent().run(project);calc=BudgetAgent().run(project);evidence=EvidenceAgent().run(project)
    review=CrossReviewAgent().run(project,scope,calc,evidence)
    total=calc['ledger']['summary']['total_won']
    return {'status':'REVIEW_REQUIRED','title':title,'year':year,'amount_won':total,
        'agents':[scope,calc,evidence,review],'ledger_hash':calc['ledger_hash'],
        'brief':{'사업명':title,'회계연도':year,'요구액_원':total,'산출근거':calc['ledger']['items'],
                 '법적근거':'확인 필요','추가확인':scope['scope_missing']+review['human_decisions']},
        'method':'외부 LLM 호출 없이 네 Python 역할이 자료 인계·반론·재검산을 수행. 네 독립 전문가의 승인 아님.'}

