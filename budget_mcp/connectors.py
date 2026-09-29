"""Public sources only. Keys stay in environment, URLs are fixed/allowlisted.
No public-data API result is silently treated as an internal budget ledger.
"""
import json, os, hashlib, threading, time
from datetime import datetime,timezone
from urllib.parse import urlsplit,urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import URLError,HTTPError
import xml.etree.ElementTree as ET
from .money import BudgetError

MAX_RESPONSE=4*1024*1024
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise BudgetError('API 리다이렉트: 공식 주소를 재검수하세요. 인증키를 다른 호스트로 보내지 않습니다.')

def public_get(url,params):
    # Only pre-vetted endpoint callers use this internal function.
    request=Request(url+'?'+urlencode(params),headers={'User-Agent':'JibangBudgetMCP/0.1.0','Accept':'application/json, application/xml'})
    try:
        with build_opener(NoRedirect).open(request,timeout=15) as response:
            data=response.read(MAX_RESPONSE+1)
            if len(data)>MAX_RESPONSE:raise BudgetError('API 응답크기 초과: 조회 범위를 축소하세요.')
            return data
    except HTTPError as e:raise BudgetError('API HTTP 오류 '+str(e.code)+'; 조회 실패는 자료 없음이 아닙니다.') from None
    except (URLError,TimeoutError,OSError):raise BudgetError('API 네트워크 연결 실패; 자료 없음으로 해석할 수 없습니다.') from None

class PublicClient:
    def __init__(self,fetch=public_get):
        self.fetch=fetch;self.lock=threading.RLock();self.cache={};self.calls=[]
    def get(self,url,params):
        ident=hashlib.sha256((url+json.dumps(params,sort_keys=True)).encode()).hexdigest()
        with self.lock:
            now=time.monotonic();hit=self.cache.get(ident)
            if hit and now-hit[0]<300:return hit[1],True,hit[2]
            self.calls=[t for t in self.calls if now-t<60]
            if len(self.calls)>=20:raise BudgetError('이 인스턴스의 외부 API 호출 제한: 분당 20회')
            self.calls.append(now)
            data=self.fetch(url,params)
            if len(data)>MAX_RESPONSE:raise BudgetError('API 응답크기 초과')
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            fetched_at=datetime.now(timezone.utc).isoformat()
            self.cache[ident]=(now,data,fetched_at)
            return data,False,fetched_at
    def law_search(self,query,target='admrul',page=1,display=10):
        if target not in ('admrul','eflaw') or not isinstance(query,str) or not 1<=len(query)<=200 or not 1<=page<=1000 or not 1<=display<=50:
            raise BudgetError('법령 검색조건 오류')
        key=os.getenv('LAW_OC','')
        if not key:return {'status':'NOT_CONFIGURED','required_env':'LAW_OC','items':[], 'note':'인증값 미설정. 검색 결과 0건을 의미하지 않습니다.'}
        url='https://www.law.go.kr/DRF/lawSearch.do'
        params={'OC':key,'target':target,'type':'XML','query':query,'page':page,'display':display,'nw':1 if target=='admrul' else 3}
        data,cached,fetched_at=self.get(url,params)
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise BudgetError('API의 비정상 XML/HTML 응답')
        try:root=ET.fromstring(data)
        except ET.ParseError:raise BudgetError('법령 API XML 형식 오류') from None
        cnt=root.findtext('totalCnt')
        if cnt is None or not cnt.isdigit():raise BudgetError('법령 API 인증/응답구조 확인 필요; 빈 결과로 보정하지 않습니다.')
        tag='admrul' if target=='admrul' else 'law'
        items=[{c.tag:c.text for c in e} for e in root.findall(tag)]
        if int(cnt)>0 and not items:raise BudgetError('검색건수와 본문 목록 불일치')
        return {'status':'EMPTY' if int(cnt)==0 else 'PARTIAL' if int(cnt)>page*display else 'PAGE_END',
            'items':items,'total':int(cnt),'page':page,'next_page':page+1 if int(cnt)>page*display else None,
            'source_url':url,'public_parameters':{k:v for k,v in params.items() if k!='OC'},
            'retrieved_at':fetched_at,'sha256':hashlib.sha256(data).hexdigest(),
            'cached':cached,'note':'목록검색 결과입니다. 해당 연도 적용본문·별표를 검증한 법적 답변이 아닙니다.'}
    def lofin_query(self,service,params,catalog_path):
        if not catalog_path:return {'status':'NOT_CONFIGURED','items':[],'note':'운영자가 검수한 지방재정365 서비스 목록이 아직 없습니다.'}
        from pathlib import Path
        p=Path(catalog_path)
        if not p.is_file() or p.stat().st_size>1024*1024:raise BudgetError('LOFIN 목록 설정 오류')
        entries=json.loads(p.read_text('utf-8'))
        if not isinstance(entries,list) or len(entries)>300:raise BudgetError('LOFIN 목록 형식 오류')
        entry=next((x for x in entries if x.get('id')==service),None)
        if not entry or entry.get('enabled') is not True:raise BudgetError('검수·활성화된 서비스 ID가 아닙니다.')
        endpoint=entry.get('endpoint','');u=urlsplit(endpoint)
        approved_hosts={'www.lofin365.go.kr','lofin365.go.kr','lofin.mois.go.kr','www.lofin.mois.go.kr'}
        if u.scheme!='https' or u.hostname not in approved_hosts or u.port not in (None,443) or u.username or u.password or u.query or u.fragment:
            raise BudgetError('허용된 공식 HTTPS endpoint만 사용 가능합니다.')
        if not entry.get('source_url') or not entry.get('reviewed_at') or not entry.get('reviewed_by'):raise BudgetError('명세 검수 메타정보 필요')
        if not isinstance(params,dict) or any(k not in entry.get('allowed_params',[]) for k in params):raise BudgetError('허용되지 않은 API 검색변수')
        if any(not isinstance(v,(str,int)) or isinstance(v,bool) or len(str(v))>100 for v in params.values()):raise BudgetError('API 파라미터는 짧은 문자열/정수만 허용')
        if any(k not in params for k in entry.get('required_params',[])):raise BudgetError('필수 검색조건 누락')
        key=os.getenv('LOFIN_API_KEY','')
        if not key:return {'status':'NOT_CONFIGURED','required_env':'LOFIN_API_KEY','items':[]}
        keyparam=entry.get('key_param','Key')
        if keyparam in params:raise BudgetError('인증키 직접 입력은 금지합니다.')
        final={**entry.get('fixed_params',{}),**params,keyparam:key}
        data,cached,fetched_at=self.get(endpoint,final)
        try:payload=json.loads(data)
        except (json.JSONDecodeError,UnicodeError):raise BudgetError('LOFIN 응답이 JSON이 아닙니다. 반환형식/명세를 확인하세요.') from None
        status_codes=[];rows=[];totals=[]
        def visit(obj,depth=0):
            if depth>20:raise BudgetError('API 중첩 깊이 초과')
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k.upper()=='CODE' and isinstance(v,str):status_codes.append(v)
                    elif k=='row' and isinstance(v,list):rows.extend(v)
                    elif k=='list_total_count':totals.append(v)
                    else:visit(v,depth+1)
            elif isinstance(obj,list):
                for x in obj:visit(x,depth+1)
        visit(payload)
        if any(c.startswith('ERROR') for c in status_codes):raise BudgetError('LOFIN 오류 코드: '+','.join(c for c in status_codes if c.startswith('ERROR')))
        if not rows and 'INFO-200' not in status_codes:raise BudgetError('LOFIN 응답구조 미확인: 자료 없음으로 보정하지 않습니다.')
        return {'status':'EMPTY' if not rows else 'PAGE_ONLY','items':rows[:200],
                'returned_rows':len(rows),'truncated':len(rows)>200,'total_count_reported':totals,
                'source_url':endpoint,'params':params,'cached':cached,'sha256':hashlib.sha256(data).hexdigest(),
                'retrieved_at':fetched_at,
                'note':'공개데이터 원시행입니다. 단위·회계·연도·단계·지역코드 검증 후 별도로 구조화해야 합니다.'}

