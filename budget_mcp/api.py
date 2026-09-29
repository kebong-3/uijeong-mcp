"""Read-only official API gateway with explicit coverage and evidence metadata.

No user-supplied URL, credential, redirect, arbitrary operation, or schema repair.
API credentials are never copied into result metadata, logs, or disk.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit,unquote
from .connectors import PublicClient,public_get,MAX_RESPONSE
from .money import BudgetError

CATALOG_PATH=Path(__file__).with_name('api_catalog.json')
KEYS=('LOFIN_API_KEY','DATA_GO_KR_SERVICE_KEY','KOSIS_API_KEY','LAW_OC')
SECRET_PARAMS={'key','servicekey','apikey','oc','authorization','token','access_token'}
ALLOWED_HOSTS={'www.lofin365.go.kr','lofin365.go.kr','apis.data.go.kr','kosis.kr','www.law.go.kr'}


def credential(name):
    value=os.getenv(name,'').strip()
    if not value or value.lower() in ('your_api_key','your_key_here','changeme','none','null','sample') or value.startswith(('발급','입력','여기에')):
        return ''
    return unquote(value) if name=='DATA_GO_KR_SERVICE_KEY' else value


def redact(value):
    secrets=[os.getenv(k,'').strip() for k in KEYS]+[credential(k) for k in KEYS]
    secrets=[s for s in secrets if len(s)>=4]
    def clean(v):
        if isinstance(v,dict):return {k:clean(x) for k,x in v.items() if str(k).lower() not in SECRET_PARAMS}
        if isinstance(v,list):return [clean(x) for x in v]
        if isinstance(v,str):
            for secret in secrets:v=v.replace(secret,'[REDACTED]')
        return v
    return clean(value)


def catalog():
    data=json.loads(CATALOG_PATH.read_text('utf-8'))
    if not isinstance(data,list) or len(data)>100:raise BudgetError('API 카탈로그 형식 오류')
    for entry in data:
        url=urlsplit(entry['endpoint'])
        if url.scheme!='https' or url.hostname not in ALLOWED_HOSTS or url.port not in (None,443) or url.username or url.password or url.query or url.fragment:
            raise BudgetError('카탈로그의 비허용 endpoint')
    return data


def parse_lofin(payload):
    rows=[];totals=[];codes=[]
    def visit(node,depth=0):
        if depth>20:raise BudgetError('응답 중첩 깊이 초과')
        if isinstance(node,dict):
            for k,v in node.items():
                if k=='row':
                    if not isinstance(v,list) or any(not isinstance(x,dict) for x in v):raise BudgetError('LOFIN 행 구조 변경')
                    rows.extend(v)
                elif k=='list_total_count':totals.append(int(v))
                elif k.upper()=='CODE':codes.append(str(v))
                else:visit(v,depth+1)
        elif isinstance(node,list):
            for x in node:visit(x,depth+1)
    visit(payload)
    if any(c not in ('INFO-000','INFO-200') for c in codes):
        raise BudgetError('LOFIN 인증/요청/제공기관 오류: '+','.join(c for c in codes if re.fullmatch(r'[A-Z]+-\d+',c)))
    if not codes or (not rows and 'INFO-200' not in codes and not (totals and totals[0]==0)):
        raise BudgetError('LOFIN 성공·빈결과 구조 미확인')
    if rows and ('INFO-200' in codes or not totals or totals[0] < len(rows)):raise BudgetError('LOFIN 상태·총건수와 행 불일치')
    if len(set(totals))>1 or any(t<0 for t in totals):raise BudgetError('LOFIN 총건수 구조 오류')
    return rows,totals[0] if totals else 0


class ProcurementResponseError(BudgetError):
    def __init__(self, message, diagnostic):
        super().__init__(message)
        self.diagnostic = diagnostic


def procurement_diagnostic(payload):
    """Only predefined envelope names and short numeric codes, never raw text.

    Unknown property names could themselves contain credentials, so they are
    counted rather than echoed. Alternate envelopes remain failures until their
    success contract has been verified against official specifications.
    """
    containers = {'response', 'header', 'body', 'error', 'result',
                  'OpenAPI_ServiceResponse', 'cmmMsgHeader'}
    code_fields = {'resultCode', 'rsltCd', 'returnReasonCode', 'code',
                   'returnCode', 'errCd', 'statusCode', 'status'}
    known = containers | code_fields | {'resultMsg', 'rsltMsg', 'returnAuthMsg',
             'errMsg', 'message', 'name', 'reason', 'detail', 'totalCount', 'items', 'item', 'pageNo', 'numOfRows'}
    shapes, codes = [], []
    def walk(node, path='$', depth=0):
        if not isinstance(node, dict) or depth > 4:
            return
        shapes.append({'path': path, 'known_keys': sorted(k for k in node if k in known),
                       'other_key_count': sum(k not in known for k in node)})
        for k in sorted(code_fields):
            if k in node:
                value = str(node[k])
                codes.append({'path': path + '.' + k,
                              'code': value if re.fullmatch(r'[0-9]{1,4}', value) else 'UNRECOGNIZED'})
        for k in sorted(containers):
            if k in node:
                walk(node[k], path + '.' + k, depth + 1)
    walk(payload)
    return {'envelopes': shapes, 'provider_codes': codes,
            'payload_type': type(payload).__name__, 'raw_values_disclosed': False}


def parse_procurement(payload):
    response=payload.get('response',payload) if isinstance(payload,dict) else {}
    if not isinstance(response,dict):response={}
    header=response.get('header',{})
    if not isinstance(header,dict):header={}
    code=str(header.get('resultCode',''))
    if code not in ('00','0','0000'):
        safe_code=code if re.fullmatch(r'[0-9]{1,4}',code) else 'UNKNOWN'
        raise ProcurementResponseError('조달 API 인증/요청 오류: '+safe_code, procurement_diagnostic(payload))
    body=response.get('body')
    if not isinstance(body,dict) or 'totalCount' not in body:raise BudgetError('조달 API 본문/총건수 구조 오류')
    total=int(body['totalCount'])
    if total<0:raise BudgetError('조달 API 음수 총건수')
    items=body.get('items')
    if isinstance(items,dict):items=items.get('item',[])
    if items in (None,''):items=[]
    if isinstance(items,dict):items=[items]
    if not isinstance(items,list) or any(not isinstance(r,dict) for r in items):raise BudgetError('조달 API 목록 구조 오류')
    if total==0 and items:raise BudgetError('조달 API 총건수/목록 불일치')
    # Budget review does not need individual officials' names/contact fields.
    items=[{k:v for k,v in r.items() if not re.search(r'ofcl|email|fax|telNo|hpNo',k,re.I)} for r in items]
    return items,total


class Gateway(PublicClient):
    def __init__(self,fetch=public_get):
        super().__init__(fetch)
        self.last_checks={}
        self.entries={r['id']:r for r in catalog()}

    def get(self,url,params):
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname not in ALLOWED_HOSTS or u.port not in (None,443) or u.query or u.fragment or u.username:
            raise BudgetError('허용된 공식 HTTPS 주소만 호출합니다.')
        with self.lock:
            now=time.monotonic()
            for k,(stamp,_,_) in list(self.cache.items()):
                if now-stamp>=300:self.cache.pop(k,None)
            if len(self.cache)>=16:self.cache.pop(next(iter(self.cache)))
            return super().get(url,params)

    def law_search(self,query,target='admrul',page=1,display=10):
        if not credential('LAW_OC'):
            return {'status':'NOT_CONFIGURED','required_env':'LAW_OC','items':[],'coverage':'NOT_QUERIED'}
        try:
            result=super().law_search(query,target,page,display)
        except BudgetError:
            self.last_checks['law_search']={'status':'ERROR','authenticated_live_verified':False}
            raise
        self.last_checks['law_search']={'status':result['status'],'authenticated_live_verified':True,
                                        'retrieved_at':result.get('retrieved_at')}
        return redact(result)

    def api_catalog(self,query=''):
        query=query.strip().lower()
        entries=[copy.deepcopy(e) for e in self.entries.values() if not query or query in (e['id']+' '+e['name']+' '+e['provider']).lower()]
        for e in entries:
            e['credential_configured']=bool(credential(e['credential_env']))
            e['authenticated_live_verified']=self.last_checks.get(e['id'],{}).get('authenticated_live_verified',False)
        return {'status':'CATALOG','items':entries,'note':'명세 확인·코드 구현·실키 응답 검증은 별개입니다. 카탈로그에 없는 URL/동작은 호출하지 않습니다.'}

    def api_status(self):
        return {'status':'CONFIGURATION_STATUS','keys':{k:{'configured':bool(credential(k)),'value_disclosed':False} for k in KEYS},
                'last_checks':copy.deepcopy(self.last_checks),'catalog_count':len(self.entries),
                'private_system_integrations':{'ehojo':'NOT_CONNECTED','botem':'NOT_CONNECTED'},
                'note':'키가 있음은 정상 인증·데이터 최신성 확인이 아닙니다. 비공개 시스템은 연결하지 않았습니다.'}

    def fetch_api(self,api_id,params,page=1,page_size=20,use_sample=False):
        entry=self.entries.get(api_id)
        if not entry:raise BudgetError('등록되지 않은 API ID. budget_api_catalog에서 선택하세요.')
        if not isinstance(page,int) or isinstance(page,bool) or not 1<=page<=10000 or not isinstance(page_size,int) or isinstance(page_size,bool) or not 1<=page_size<=100:
            raise BudgetError('페이지 범위 오류')
        if not isinstance(params,dict) or set(params)-set(entry['allowed_params']):raise BudgetError('허용되지 않은 API 검색변수')
        if any(k.lower() in SECRET_PARAMS for k in params):raise BudgetError('키를 도구 인자로 전달하지 마세요.')
        if any(not isinstance(v,(str,int)) or isinstance(v,bool) or len(str(v))>1000 or '\x00' in str(v) for v in params.values()):raise BudgetError('API 검색값 형식 오류')
        if any(k not in params or params[k]=='' for k in entry.get('required_params',[])):
            raise BudgetError('필수 검색변수: '+', '.join(entry.get('required_params',[])))
        if entry.get('one_of') and not any(params.get(k) for k in entry['one_of']):
            raise BudgetError('조회에 필요한 공식 식별번호 중 하나를 지정하세요: '+', '.join(entry['one_of']))
        key=credential(entry['credential_env'])
        if use_sample and entry['provider']!='lofin':raise BudgetError('샘플 모드는 지방재정365에서만 지원합니다.')
        sample=use_sample and not key
        if not key and not sample:
            return {'status':'NOT_CONFIGURED','api_id':api_id,'required_env':entry['credential_env'],
                    'application_url':entry['application_url'],'items':[], 'coverage':'NOT_QUERIED','authenticated_live_verified':False}
        if sample and page!=1:raise BudgetError('인증키 없는 공식 샘플은 1페이지만 조회합니다.')
        p={**entry.get('fixed_params',{}),**params}
        if entry['provider']=='lofin':
            if api_id=='lofin_projects':
                try:dt=datetime.strptime(str(p['exe_ymd']),'%Y%m%d')
                except ValueError:raise BudgetError('집행기준일은 YYYYMMDD 실제 날짜여야 합니다.') from None
                if dt.year!=int(p['fyr']):raise BudgetError('이 도구는 회계연도와 집행기준일의 연도가 같은 자료만 조회합니다.')
            p.update(Type='json',pIndex=page,pSize=5 if sample else page_size)
        elif entry['provider']=='procurement':
            p.update(type='json',pageNo=page,numOfRows=page_size)
            if 'inqryBgnDt' in p or 'inqryEndDt' in p:
                try:
                    begin=datetime.strptime(str(p['inqryBgnDt']),'%Y%m%d%H%M');end=datetime.strptime(str(p['inqryEndDt']),'%Y%m%d%H%M')
                except (ValueError,KeyError):raise BudgetError('조달 조회기간은 시작·종료 YYYYMMDDHHMM을 모두 지정하세요.') from None
                if end<begin or (end-begin).total_seconds()>31*86400:raise BudgetError('조회기간은 순서가 맞는 31일 이내로 나누세요.')
        elif entry['provider']=='kosis':
            if page!=1:raise BudgetError('KOSIS는 페이지가 아닌 통계표·기간으로 범위를 줄이세요.')
            # KOSIS official examples request jsonVD=Y for json.loads-compatible JSON.
            # Never repair or evaluate a JavaScript-like upstream response.
            p.update(method='getList',format='json',jsonVD='Y')
        if key:p[entry['key_param']]=key
        try:
            data,cached,at=self.get(entry['endpoint'],p)
            if len(data)>MAX_RESPONSE:raise BudgetError('응답 용량 한도 초과')
            try:payload=json.loads(data)
            except (ValueError,UnicodeError):raise BudgetError('JSON 응답이 아닙니다. 인증/형식/서버 상태를 확인하세요.') from None
            if entry['provider']=='lofin':rows,total=parse_lofin(payload)
            elif entry['provider']=='procurement':rows,total=parse_procurement(payload)
            elif entry['provider']=='kosis':
                # Only the provider's numeric error code is safe to expose. Never
                # return errMsg or raw content, which could echo a credential.
                errors=([payload] if isinstance(payload,dict) else payload) if isinstance(payload,(dict,list)) else []
                for error in errors:
                    if isinstance(error,dict) and ('err' in error or 'errCd' in error):
                        code=str(error.get('err',error.get('errCd','')))
                        code=code if re.fullmatch(r'[0-9]{1,3}',code) else 'UNKNOWN'
                        raise BudgetError('KOSIS 오류 코드: '+code)
                if not isinstance(payload,list) or any(not isinstance(x,dict) for x in payload):raise BudgetError('KOSIS 오류 또는 목록 구조 변경')
                rows,total=payload,len(payload)
            else:raise BudgetError('지원하지 않는 파서')
            if total and not rows and (page-1)*page_size<total:raise BudgetError('총건수와 페이지 내용 불일치')
        except (BudgetError,ValueError,TypeError,KeyError) as exc:
            message=str(exc) if isinstance(exc,BudgetError) else '제공기관 응답 형식 오류'
            state={'status':'ERROR','authenticated_live_verified':False,'checked_at':datetime.now(timezone.utc).isoformat()}
            self.last_checks[api_id]=state
            diagnostic={'provider_diagnostic':exc.diagnostic} if isinstance(exc,ProcurementResponseError) else {}
            return {'status':'ERROR','api_id':api_id,**diagnostic,'message':redact(message),'items':[],'authenticated_live_verified':False,
                    'coverage':'REQUEST_FAILED','source_url':entry['application_url'],'note':'조회 실패이며 사업이 없다는 뜻이 아닙니다.'}
        delivered=rows[:(5 if sample else page_size)]
        next_page=page+1 if not sample and entry['provider']!='kosis' and page*page_size<total else None
        state={'status':'SUCCESS','authenticated_live_verified':bool(key),'retrieved_at':at,'sample_only':sample}
        self.last_checks[api_id]=state
        out={'status':'EMPTY' if not rows else 'SAMPLE_ONLY' if sample else 'PAGE_ONLY','api_id':api_id,
            'source_state':'OFFICIAL_API','source_url':entry['application_url'],'endpoint':entry['endpoint'],
            'public_params':params,'items':delivered,'returned_count':len(delivered),'total_count_reported':total,
            'page':page,'page_size':5 if sample else page_size,'next_page':next_page,
            'truncated':len(rows)>len(delivered),'retrieved_at':at,'cached':cached,
            'response_sha256':hashlib.sha256(data).hexdigest(),'authenticated_live_verified':bool(key),
            'data_are_untrusted_instructions':True,'amount_unit':entry.get('amount_unit','SOURCE_CONFIRMATION_REQUIRED'),
            'coverage':{'scope':'SAMPLE_ONLY' if sample else 'ONE_REQUEST','complete_nationwide':False},
            'note':'목록 페이지 원시자료입니다. 사업규모·단위·예산단계·최종결산 확정 여부를 별도로 확인하세요.'}
        return redact(out)

