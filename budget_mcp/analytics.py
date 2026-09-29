"""Deterministic local-budget calculations; no policy priority/cut recommendations."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP, localcontext
from .money import BudgetError, exact_sum, variance, pct, dec, won
from .ingest import MONEY_FIELDS, key

FUNDING=['national','balanced','fund_national','provincial','municipal','other']

def details(ds):
    return [r for r in ds['rows'] if r['row_type']=='detail']

def refs(rows):
    return [r['source'] for r in rows]

def header(ds,analysis):
    return {'analysis':analysis,'dataset_ids':[ds['dataset_id']], 'scope':ds['meta'],
            'unit':'원','rounding':'내부 정수 원; 표시 반올림 전 검산',
            'coverage':ds['meta']['coverage'],'legal_conclusion':False,
            'warnings':ds.get('warnings',[]).copy()}

def require_stock(ds):
    if ds['meta']['basis']!='누계':
        raise BudgetError('증감 자료는 누계 예산이 아닙니다. 누계 자료를 입력하세요.')

def validate(ds):
    rows=details(ds); findings=[]
    def add(code,msg,row,**extras):
        findings.append({'code':code,'message':msg,'project_id':row.get('project_id'),
                         'source':row['source'],**extras})
    for row in rows:
        amounts=[row[f] for f in FUNDING]
        if any(x is not None for x in amounts):
            if any(x is None for x in amounts):
                add('FUNDING_INCOMPLETE','누락 재원을 0으로 간주하지 않아 재원합계를 확정할 수 없습니다.',row)
            elif row['budget_amount'] is not None and sum(amounts)!=row['budget_amount']:
                add('FUNDING_MISMATCH','재원합계와 해당 행 예산액이 다릅니다. 재원 열의 범위도 확인하세요.',row,
                    difference_won=sum(amounts)-row['budget_amount'])
        for f in MONEY_FIELDS:
            if row[f] is not None and row[f]<0:
                add('NEGATIVE_AMOUNT','음수 정정·환급·감액 등 성격 확인 필요',row,field=f)
        if ds['meta']['basis']=='누계':
            av,sp=row['available_budget'],row['expenditure']
            if av is not None and sp is not None and sp>av:
                add('SPENDING_EXCEEDS_AVAILABLE','지출액이 예산현액보다 큽니다.',row)
            fields=['available_budget','expenditure','carryover_next','subsidy_return','unspent_declared']
            if all(row[f] is not None for f in fields):
                residual=row['available_budget']-sum(row[f] for f in fields[1:])
                if residual:
                    add('SETTLEMENT_EQUATION_MISMATCH','예산현액 = 지출+다음연도이월+보조금반납금+집행잔액 검산 불일치',row,difference_won=residual)
        rf=['assessed','collected','writeoffs','unpaid_declared']
        if all(row[f] is not None for f in rf):
            residual=row['assessed']-sum(row[f] for f in rf[1:])
            if residual:
                add('REVENUE_EQUATION_MISMATCH','징수결정 = 실제수납+정리보류+미수납 검산 불일치',row,difference_won=residual)
    checks=[]
    totals=[r for r in ds['rows'] if r['row_type']=='total']
    for f in MONEY_FIELDS:
        s=exact_sum(r[f] for r in rows)
        if not any(r[f] is not None for r in rows) and (not totals or totals[0][f] is None):
            continue
        declared=totals[0][f] if totals else None
        status='NO_DECLARED_TOTAL'
        if s['missing_count']: status='INCOMPLETE_DETAIL_VALUES'
        elif declared is not None: status='MATCH' if declared==s['value_won'] else 'MISMATCH'
        checks.append({'field':f,**s,'declared_total_won':declared,'status':status,
                       'difference_won':s['value_won']-declared if s['value_won'] is not None and declared is not None else None,
                       'total_source':totals[0]['source'] if totals else None})
    out=header(ds,'자료 정합성 검산')
    out.update(summary={'detail_rows':len(rows),'findings':len(findings),'total_checks':checks,
                        'note':'검산 통과는 지출 적법성 또는 정책 적정성을 의미하지 않습니다.'},items=findings)
    return out

def compare(before,after,field='budget_amount',project_crosswalk=None):
    if field not in MONEY_FIELDS: raise BudgetError('지원 금액 필드를 지정하세요.')
    for dim in ['authority','kind','basis']:
        if before['meta'][dim]!=after['meta'][dim]:
            raise BudgetError(dim+' 기준이 다른 자료는 바로 비교할 수 없습니다.')
    require_stock(before);require_stock(after)
    cross=project_crosswalk or {}
    if not isinstance(cross,dict) or len(set(cross.values()))!=len(cross):
        raise BudgetError('사업코드 대응표는 1:1 문자열 매핑이어야 합니다. 분할·통합 사업은 별도 재분류 필요.')
    if any(not isinstance(k,str) or not isinstance(v,str) for k,v in cross.items()):
        raise BudgetError('사업코드 대응표 형식 오류')
    old=details(before);new=details(after)
    if set(cross)-{r['project_id'] for r in old} or set(cross.values())-{r['project_id'] for r in new}:
        raise BudgetError('대응표의 사업코드가 실제 자료에 없습니다.')
    b={}; a={key(r):r for r in new}
    for r in old:
        k=list(key(r));k[1]=cross.get(k[1],k[1]);k=tuple(k)
        if k in b: raise BudgetError('사업코드 대응 후 중복: 자동 합산하지 않습니다.')
        b[k]=r
    items=[]
    for k in sorted(set(a)|set(b)):
        br,ar=b.get(k),a.get(k)
        item={'key':list(k),'project_name':(ar or br)['project_name'],
              'presence':'BOTH' if br and ar else 'ONLY_CURRENT' if ar else 'ONLY_BASE',
              **variance(br[field] if br else None,ar[field] if ar else None),
              'sources':refs([r for r in [br,ar] if r]),
              'notes':[]}
        if br and ar and br['department']!=ar['department']:
            item['notes'].append('부서 변경: 이관 여부를 확인하세요.')
        if br and ar and br['project_name']!=ar['project_name']:
            item['notes'].append('사업명 변경: 동일 코드의 사업범위 변경 여부를 확인하세요.')
        if not (br and ar): item['notes'].append('이번 자료에서의 존재 차이일 뿐 신규·폐지사업으로 확정하지 않습니다.')
        items.append(item)
    bs=exact_sum(r[field] for r in old);cs=exact_sum(r[field] for r in new)
    summary={'field':field,'base_total':bs,'current_total':cs,
             'total_change':variance(bs['value_won'],cs['value_won']),
             'both_count':sum(i['presence']=='BOTH' for i in items),
             'only_base_count':sum(i['presence']=='ONLY_BASE' for i in items),
             'only_current_count':sum(i['presence']=='ONLY_CURRENT' for i in items)}
    if bs['missing_count']==0 and cs['missing_count']==0:
        matched=sum(i['delta_won'] for i in items if i['presence']=='BOTH')
        added=sum(i['after_won'] for i in items if i['presence']=='ONLY_CURRENT')
        removed=sum(i['before_won'] for i in items if i['presence']=='ONLY_BASE')
        summary['arithmetic_bridge']={'matched_delta_won':matched,'only_current_won':added,
            'only_base_won':removed,'reconciles':matched+added-removed==cs['value_won']-bs['value_won'],
            'meaning':'입력 자료 사이의 수치 분해이며 증감 사유를 입증하지 않습니다.'}
    else: summary['arithmetic_bridge']=None
    warnings=[]
    if before['meta']['stage']!=after['meta']['stage']:
        warnings.append('편성단계가 다릅니다: 본예산-추경/요구안 비교임을 명시해야 합니다.')
    if before['meta']['coverage']=='부분' or after['meta']['coverage']=='부분':
        warnings.append('부분자료 비교: 전체 기관 예산 증감으로 일반화할 수 없습니다.')
    return {'analysis':'예산 증감 비교','dataset_ids':[before['dataset_id'],after['dataset_id']],
            'base_meta':before['meta'],'current_meta':after['meta'],'unit':'원',
            'warnings':warnings,'summary':summary,'items':items,'legal_conclusion':False}

def funding(ds,scope='시군구비',national_only=True,limit=10):
    require_stock(ds)
    if ds['meta']['kind']!='세출': raise BudgetError('재원분담 집계는 세출자료를 사용하세요.')
    if scope not in ('시군구비','시도비+시군구비') or not 1<=limit<=200:
        raise BudgetError('지방비 범위/표시건수 오류')
    groups=defaultdict(list)
    for r in details(ds):groups[(r['account'],r['project_id'])].append(r)
    items=[];excluded=[]
    for (account,pid),rs in sorted(groups.items()):
        names=set(r['project_name'] for r in rs)
        if len(names)>1: raise BudgetError('동일 사업코드에 서로 다른 사업명: '+pid)
        national=exact_sum(r[f] for r in rs for f in ['national','balanced','fund_national'])
        local=exact_sum(r[f] for r in rs for f in (['municipal'] if scope=='시군구비' else ['provincial','municipal']))
        total=exact_sum(r['budget_amount'] for r in rs)
        obj={'account':account,'project_id':pid,'project_name':rs[0]['project_name'],
             'national_won':national['value_won'],'local_burden_won':local['value_won'],
             'annual_budget_won':total['value_won'],'scope':scope,'sources':refs(rs),
             'national_rate_pct':pct(national['value_won'],total['value_won'])}
        mismatch=any(all(r[f] is not None for f in FUNDING+['budget_amount']) and sum(r[f] for f in FUNDING)!=r['budget_amount'] for r in rs)
        obj['funding_equation_status']='MISMATCH' if mismatch else 'PARTIAL' if any(r[f] is None for r in rs for f in FUNDING) else 'MATCH'
        if mismatch:
            obj['exclusion_reason']='재원합계와 예산액 불일치: 검산 후 다시 집계';excluded.append(obj)
        elif national['missing_count'] or local['missing_count'] or total['missing_count']:
            obj['exclusion_reason']='재원 또는 예산액 공란으로 비교 확정 불가';excluded.append(obj)
        elif national_only and national['value_won']<=0:
            obj['exclusion_reason']='입력자료상 국비 양수 사업이 아님';excluded.append(obj)
        else:items.append(obj)
    items.sort(key=lambda r:(-r['local_burden_won'],r['project_id'],r['account']))
    out=header(ds,'국비·지방비 분담 집계')
    out.update(summary={'national_definition':'국고보조금+균특보조금+기금보조금',
       'local_scope':scope,'annual_not_multi_year':True,'eligible_count':len(items),
       'excluded_count':len(excluded),'top_requested':limit,
       'note':'부담액 수치 내림차순이며 사업의 가치·우선순위 평가가 아닙니다.'},items=items,
       excluded=excluded, default_page_size=limit)
    return out

def execution(ds):
    require_stock(ds)
    if ds['meta']['kind']!='세출':raise BudgetError('세출자료가 필요합니다.')
    out=header(ds,'집행·결산 검산');items=[]
    for r in details(ds):
        av,sp,cm,co,ret=r['available_budget'],r['expenditure'],r['committed_unpaid'],r['carryover_next'],r['subsidy_return']
        raw=None if av is None or sp is None else av-sp
        residual=None if any(x is None for x in [av,sp,co,ret]) else av-sp-co-ret
        items.append({'project_id':r['project_id'],'project_name':r['project_name'],
            'account':r['account'],'department':r['department'],'budget_code':r['budget_code'],'line_id':r.get('line_id',''),
            'available_budget_won':av,'expenditure_won':sp,'execution_rate_pct':pct(sp,av),
            'not_spent_won':raw,'not_committed_estimate_won':None if raw is None or cm is None else raw-cm,
            'settlement_residual_won':residual,'declared_unspent_won':r['unspent_declared'],
            'settlement_difference_won':None if residual is None or r['unspent_declared'] is None else residual-r['unspent_declared'],
            'source':r['source']})
    out.update(summary={'count':len(items),'formulas':{
        'not_spent':'예산현액-지출액',
        'not_committed_estimate':'예산현액-지출액-미지급지출원인행위액',
        'settlement_residual':'예산현액-지출액-다음연도이월액-보조금반납금'},
        'note':'미집행액은 감액 가능액이 아닙니다. 미지급 계약·이월·국시비 조건과 기준일을 확인하세요.'},items=items)
    if ds['meta']['stage']!='결산':out['warnings'].append('결산 확정자료가 아닙니다. 잔액은 현재 입력값 기준 계산치입니다.')
    return out

def revenue(ds):
    require_stock(ds)
    if ds['meta']['kind']!='세입':raise BudgetError('세입자료가 필요합니다.')
    out=header(ds,'세입 차이 분해');items=[]
    for r in details(ds):
        b,a,c,w,u=[r[f] for f in ['available_budget','assessed','collected','writeoffs','unpaid_declared']]
        sub=lambda x,y: None if x is None or y is None else x-y
        rec=None if any(x is None for x in [a,c,w,u]) else a-c-w-u
        items.append({'project_id':r['project_id'],'project_name':r['project_name'],
            'account':r['account'],'department':r['department'],'budget_code':r['budget_code'],'line_id':r.get('line_id',''),
            'budget_minus_collected_won':sub(b,c),'budget_minus_assessed_won':sub(b,a),
            'assessed_minus_collected_won':sub(a,c),'assessed_minus_collected_minus_writeoffs_won':None if any(x is None for x in [a,c,w]) else a-c-w,
            'reconciliation_difference_won':rec,'collection_rate_of_assessed_pct':pct(c,a),
            'source':r['source']})
    out.update(summary={'count':len(items),'identity':'예산현액-수납액 = (예산현액-징수결정액)+(징수결정액-수납액)',
                        'note':'수치상 분해입니다. 과다추계·체납·납기차이·감면 등 실제 원인은 징수부서 자료로 확인해야 합니다.'},items=items)
    return out

def estimate_cost(components,unit='원'):
    if not isinstance(components,list) or not 1<=len(components)<=100:
        raise BudgetError('산출내역은 1~100개')
    items=[];total=0
    for x in components:
        if not isinstance(x,dict) or not x.get('name') or not x.get('basis'):
            raise BudgetError('각 내역에 name과 단가근거/가정 basis를 명시하세요.')
        price=won(x.get('unit_price'),unit)
        qty=dec(x.get('quantity'));count=dec(x.get('count','1'));period=dec(x.get('periods','1'))
        if price is None or min(Decimal(price),qty,count,period)<0:raise BudgetError('음수/공란 산출입력은 불가합니다.')
        with localcontext() as ctx:
            ctx.prec=60
            v=Decimal(price)*qty*count*period
            if v>Decimal('10000000000000000'):raise BudgetError('산출액 제한 초과')
            amount=int(v.quantize(Decimal(1),rounding=ROUND_HALF_UP))
        total+=amount
        items.append({'name':str(x['name']),'amount_won':amount,'formula':f'{price}원 × {qty} × {count} × {period}',
                      'basis':str(x['basis']),'rounding':'행별 원 단위 반올림'})
    if total>10**16:raise BudgetError('총액 제한 초과')
    return {'analysis':'사용자 가정에 따른 소요예산 계산','dataset_ids':[],'unit':'원',
            'summary':{'total_won':total,'note':'입력 항목만 계산합니다. 주휴·퇴직·보험료·부가세·법정단가를 자동 포함/검증하지 않습니다.'},'items':items}

def scenario(ds,rates,reason):
    require_stock(ds)
    if ds['meta']['kind']!='세출':raise BudgetError('세출자료가 필요합니다.')
    if not isinstance(rates,dict) or not rates or len(rates)>1000 or not isinstance(reason,str) or not reason.strip():
        raise BudgetError('사용자가 정한 사업별 변동률과 가정의 사유를 입력하세요.')
    known={r['project_id'] for r in details(ds)}
    if set(rates)-known:raise BudgetError('변동률에 자료에 없는 사업코드가 있습니다.')
    parsed={k:dec(v) for k,v in rates.items()}
    if any(v<-100 or v>1000 for v in parsed.values()):raise BudgetError('변동률은 -100~1000%')
    items=[]
    for r in details(ds):
        base=r['budget_amount'];rate=parsed.get(r['project_id'],Decimal(0))
        with localcontext() as ctx:
            ctx.prec=60
            future=None if base is None else int((Decimal(base)*(1+rate/100)).quantize(Decimal(1),rounding=ROUND_HALF_UP))
        if future is not None and abs(future)>10**16:raise BudgetError('시나리오 금액 제한 초과')
        items.append({'project_id':r['project_id'],'project_name':r['project_name'],
            'account':r['account'],'department':r['department'],'budget_code':r['budget_code'],'line_id':r.get('line_id',''),'base_won':base,
                      'change_rate_pct':str(rate),'scenario_won':future,
                      'delta_won':None if base is None else future-base,'source':r['source']})
    out=header(ds,'사용자 지정 예산 시나리오')
    out.update(summary={'reason':reason,'base_total':exact_sum(i['base_won'] for i in items),
                        'scenario_total':exact_sum(i['scenario_won'] for i in items),
                        'note':'산술 가정일 뿐 감액 권고나 적법성 판단이 아닙니다. 국시비 변경·의무부담·계약조건은 별도 확인.'},items=items)
    return out

def settlement(receipts,expenditures,carryovers,grant_returns,unit='원'):
    values=[won(x,unit) for x in [receipts,expenditures,carryovers,grant_returns]]
    if any(x is None or x<0 for x in values):raise BudgetError('결산 항목은 중복 없는 0 이상 확정금액을 명시하세요.')
    r,e,c,g=values
    return {'analysis':'결산 잉여금 단순 검산','unit':'원','dataset_ids':[],
            'summary':{'gross_surplus_won':r-e,'net_surplus_calculation_won':r-e-c-g,
            'formula':'세입결산액-세출결산액-다음연도이월액-국시도비보조금실제반납금 등 입력 반납액',
            'note':'입력한 이월액과 반납액의 중복 배제 및 결산서 공식 산식·반납범위 확인 필요. 연도별 적용지침을 대신하지 않습니다.'},
            'items':[{'receipts_won':r,'expenditures_won':e,'carryovers_won':c,'grant_returns_won':g}]}

def group(ds,by=None,fields=None,code_prefixes=None):
    """Aggregate explicit dimensions, not inferred fiscal classifications."""
    by=by or ['department'];fields=fields or ['budget_amount']
    allowed=['department','account','budget_code','project_id']
    if not isinstance(by,list) or not 1<=len(by)<=4 or len(set(by))!=len(by) or any(k not in allowed for k in by):
        raise BudgetError('집계기준은 부서·회계·통계목·사업코드 중 중복 없는 목록')
    if not isinstance(fields,list) or not 1<=len(fields)<=len(MONEY_FIELDS) or len(set(fields))!=len(fields) or any(f not in MONEY_FIELDS for f in fields):
        raise BudgetError('집계 금액필드 오류')
    prefixes=code_prefixes or []
    if not isinstance(prefixes,list) or len(prefixes)>30 or any(not isinstance(p,str) or not p.strip() or len(p)>30 for p in prefixes):
        raise BudgetError('통계목 접두어는 비어있지 않은 문자열 목록')
    allrows=details(ds);rows=[r for r in allrows if not prefixes or any(r['budget_code'].startswith(p) for p in prefixes)]
    groups=defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in by)].append(r)
    items=[]
    for k,rs in sorted(groups.items()):
        item={**dict(zip(by,k)),'row_count':len(rs),'sources':refs(rs),'missing_counts':{},'known_subtotals_won':{}}
        for f in fields:
            s=exact_sum(r[f] for r in rs);item[f+'_won']=s['value_won'];item['missing_counts'][f]=s['missing_count'];item['known_subtotals_won'][f]=s['known_subtotal_won']
        items.append(item)
    out=header(ds,'명시적 기준별 예산 집계')
    out.update(summary={'group_by':by,'fields':fields,'code_prefixes':prefixes,'matched_rows':len(rows),'all_detail_rows':len(allrows),
                        'filtered_scope':bool(prefixes),'totals':{f:exact_sum(r[f] for r in rows) for f in fields},
                        'note':'통계목 코드의 정책적 의미·당해 연도 분류는 자동 인증하지 않습니다. 합계/소계행 제외. 공란 포함 그룹의 합계는 미확정.'},items=items)
    return out

