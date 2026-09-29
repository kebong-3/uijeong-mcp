"""Source-aware budget procedure questions, not automated legal opinions."""
from pathlib import Path
from datetime import date
import json,hashlib
from urllib.parse import urlsplit
from .money import BudgetError
from .ingest import safe_file

SOURCES=[
 {'id':'lofin','name':'지방재정365','url':'https://www.lofin365.go.kr/',
  'purpose':'예산·집행·결산·유사단체 재정 비교','status':'공개자료 플랫폼 확인; 실제 서비스코드·승인·응답은 연결 전 확인'},
 {'id':'law','name':'국가법령정보 공동활용','url':'https://open.law.go.kr/LSO/openApi/guideList.do',
  'purpose':'지방재정법·지방회계법·보조금법령·행정규칙 검색','status':'목록검색 어댑터 구현; 실키 호출 미검증'},
 {'id':'law_admrul','name':'행정규칙 목록 API','url':'https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=admrulListGuide',
  'purpose':'예산편성 운영기준·회계관리 훈령 등의 목록·시행일 확인','status':'공식 명세 확인'},
 {'id':'mois','name':'행정안전부 지방재정 업무','url':'https://www.mois.go.kr/frt/sub/a06/b07/localTaxMainBis/screen.do',
  'purpose':'연도별 운영기준·업무편람 원문 확보','status':'최신 연도 원문은 별도 확보·검수 필요'},
 {'id':'kosis','name':'KOSIS 공유서비스','url':'https://kosis.kr/openapi/index/index.jsp',
  'purpose':'대상 인구·시설수·사업량 추정에 필요한 통계','status':'공식 서비스 확인; 초기판 연결 미구현'},
 {'id':'procurement','name':'나라장터 계약과정통합공개','url':'https://www.data.go.kr/data/15129459/openapi.do',
  'purpose':'유사 계약의 범위·시기·금액을 확인해 단가근거 보강','status':'공식 서비스 확인; 초기판 연결 미구현'},
 {'id':'shopping','name':'나라장터쇼핑몰 품목정보','url':'https://www.data.go.kr/data/15129471/openapi.do',
  'purpose':'자산·물품 단가의 비교조건 확인','status':'공식 서비스 확인; 초기판 연결 미구현'}
]
QUESTIONS={
 '보조금': [('재정지원 근거','사업의 법령·조례·예산상 지원 근거 및 지원대상은 무엇인가?'),
           ('재원분담','국고·균특·기금·시도비·시군구비와 자체 추가부담을 구분했는가?'),
           ('절차','해당 연도 보조금 관리기준과 기관 내부절차의 적용대상·시점은 확인했는가?'),
           ('정산','반납금·이자·집행잔액을 구분하고 중복 계상하지 않았는가?')],
 '시설': [('사업 범위','토지·공사·설계·감리·물품·운영비와 다년도 총사업비를 구분했는가?'),
         ('사전절차','투자심사·중기재정계획·공유재산 절차 등의 적용 여부를 최신 기준에서 확인했는가?'),
         ('재정부담','시설 개관 후 인력·유지보수·운영비를 별도로 산출했는가?')],
 '위탁': [('업무 성격','민간위탁·공기관위탁·일반용역 중 실제 사무와 계약 성격은 무엇인가?'),
         ('근거·절차','위탁근거, 동의·심사·계약 절차 적용 여부를 원문에서 확인했는가?'),
         ('정산','직접사업비·관리비·부가세·정산조건을 구분했는가?')],
 '인건비':[('산식','인원·기간·근로시간·단가의 기준연도를 명시했는가?'),
           ('법정부담','주휴·연차·퇴직·사용자보험료의 적용대상 및 산출근거를 별도로 검토했는가?')],
 '행사':[('범위','행사운영·참가자 실비·보조·용역·시설비 등의 실질을 구분했는가?'),
         ('누락·중복','부서·회계 간 동일 비용이나 재원 중복이 있는가?')],
 '기금':[('성격','일반회계/특별회계/기금 간 전출입·예탁·예수금을 구분했는가?'),
         ('기준','기금 조례와 해당 연도 기금운용계획 수립기준의 적용 여부를 확인했는가?')],
 '일반':[('연도·단계','요구안·본예산·추경·예산현액·결산 중 어떤 금액인가?'),
         ('통계목','지출의 실질과 당해 연도 편성목·통계목 설명을 대조했는가?'),
         ('근거','단가·물량·기간과 근거 문서의 해당 페이지/조문을 제시했는가?')]
}

def checklist(topic,year):
    if topic not in QUESTIONS or not 1990<=year<=2100:raise BudgetError('지원 주제/연도 오류')
    items=[{'category':a,'question':b,'status':'확인 필요'} for a,b in QUESTIONS['일반']+(QUESTIONS[topic] if topic!='일반' else [])]
    return {'topic':topic,'year':year,'items':items,'basis_verified':False,
            'note':'검토 질문 목록입니다. 특정 심사·동의 의무나 금액기준의 적용을 확정하지 않습니다.',
            'source_candidates':[s for s in SOURCES if s['id'] in ('law','law_admrul','mois')]}

def search_local_basis(input_dir,file,query,as_of,year):
    """Search administrator-curated excerpts with mandatory source/version dates.
    A matching excerpt is evidence to review, not a model-generated legal opinion.
    """
    when=date.fromisoformat(as_of)
    if not isinstance(query,str) or not query.strip() or len(query)>200:raise BudgetError('검색어 오류')
    p=safe_file(input_dir,file)
    if p.suffix.lower()!='.json' or p.stat().st_size>4*1024*1024:raise BudgetError('근거목록은 4MB 이하 JSON')
    raw=p.read_bytes();entries=json.loads(raw)
    if not isinstance(entries,list) or len(entries)>2000:raise BudgetError('근거목록 형식/길이 오류')
    accepted=[];rejected=0
    for entry in entries:
        needed=['id','title','text','source_url','source_locator','effective_from','effective_to','fiscal_year','reviewed_by','reviewed_at']
        if not isinstance(entry,dict) or any(k not in entry for k in needed):raise BudgetError('근거 메타정보 누락')
        url=urlsplit(entry['source_url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password:raise BudgetError('근거는 HTTPS 출처 필요')
        if len(entry['text'])>12000 or len(entry['title'])>300:raise BudgetError('근거 본문 길이 제한')
        start=date.fromisoformat(entry['effective_from']);end=date.fromisoformat(entry['effective_to'])
        reviewed=date.fromisoformat(entry['reviewed_at'])
        if end<start or reviewed>when:raise BudgetError('시행기간/검수일 오류')
        if not entry['reviewed_by']:raise BudgetError('검수 담당자 표기 필요')
        if not (start<=when<=end) or entry['fiscal_year']!=year:
            rejected+=1;continue
        text=(entry['title']+' '+entry['text']).casefold()
        if all(t.casefold() in text for t in query.split()):
            accepted.append({**entry,'registry_sha256':hashlib.sha256(raw).hexdigest(),
                             'verification':'LOCAL_CURATED_EXCERPT_NOT_LIVE_VERIFIED'})
    return {'query':query,'as_of':as_of,'fiscal_year':year,'items':accepted[:30],
            'matched_count':len(accepted),'truncated':len(accepted)>30,'excluded_by_date_or_year':rejected,
            'note':'검수 메타정보는 등록자의 기재입니다. 실제 최신성·원문 일치를 서버가 인증하지 않습니다.'}

