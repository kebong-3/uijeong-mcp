import {
  deepFindRecords,
  normalizeLawChange,
  normalizeArticleChange,
  normalizeLocalLink,
  normalizeOrdinance,
  buildImpact
} from '../lib/impact-engine.mjs';

const BASE='https://www.law.go.kr/DRF/lawSearch.do';
const OC=process.env.LAW_OC || '';
const AGENCY=process.env.AGENCY_CODE || '3600000';
const PARENT=process.env.PARENT_AGENCY_CODE || '6290000';

const esc=(v='')=>String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const date8=(v='')=>String(v).replace(/\D/g,'').slice(0,8);
const fmt=(v='')=>{const s=date8(v);return s.length===8?s.slice(0,4)+'.'+s.slice(4,6)+'.'+s.slice(6,8):'-';};

async function lawFetch(params){
  if(!OC) throw new Error('LAW_OC_NOT_CONFIGURED');
  const u=new URL(BASE);
  for(const [k,v] of Object.entries({OC,type:'JSON',...params})) if(v!==''&&v!=null) u.searchParams.set(k,String(v));
  const r=await fetch(u);
  if(!r.ok) throw new Error('LAW_API_'+r.status);
  return await r.json();
}

function totalOf(data){
  const found=[];
  const walk=(v)=>{
    if(!v||typeof v!=='object') return;
    if(Array.isArray(v)) return v.forEach(walk);
    for(const [k,x] of Object.entries(v)){
      if(/totalCnt|검색건수|검색결과개수/i.test(k)&&!Number.isNaN(Number(x))) found.push(Number(x));
      walk(x);
    }
  };
  walk(data);
  return found.length?Math.max(...found):0;
}

async function paged(params,signatures,maxPages=8){
  const first=await lawFetch({...params,display:100,page:1});
  let rows=deepFindRecords(first,signatures);
  const total=totalOf(first);
  const pages=Math.min(maxPages,Math.max(1,Math.ceil(total/100)));
  for(let p=2;p<=pages;p++){
    const data=await lawFetch({...params,display:100,page:p});
    rows=rows.concat(deepFindRecords(data,signatures));
  }
  return rows;
}

async function changes(date){
  const [lawsRaw,articlesRaw]=await Promise.all([
    paged({target:'lsHstInf',regDt:date},['법령명한글','법령ID','법령일련번호'],6),
    paged({target:'lsJoHstInf',regDt:date},['조문번호','조문정보','조문개정일'],8)
  ]);
  return {
    laws:lawsRaw.map(normalizeLawChange).filter(x=>x.lawName),
    articles:articlesRaw.map(normalizeArticleChange).filter(x=>x.lawName||x.lawId)
  };
}

async function search(q){
  const rows=await paged({target:'law',search:1,query:q,nw:1,sort:'ddes'},['법령명한글','법령ID','법령일련번호'],2);
  return rows.map(normalizeLawChange).filter(x=>x.lawName).slice(0,50);
}

async function impact(lawId,lawName,date){
  const linksRaw=await paged({target:'lnkOrg',org:AGENCY},['자치법규명','법령명한글','법령ID'],12);
  const bodyRaw=await paged({target:'ordin',nw:1,search:2,query:lawName,org:PARENT,sborg:AGENCY},['자치법규명','지자체기관명','자치법규ID'],3);
  const c=date?await changes(date):{laws:[],articles:[]};
  const change=c.laws.find(x=>(lawId&&x.lawId===lawId)||(lawName&&x.lawName===lawName)) || {lawId,lawName,effectiveDate:'',changeType:''};
  return buildImpact(
    change,
    linksRaw.map(normalizeLocalLink).filter(x=>x.ordinanceName),
    bodyRaw.map(normalizeOrdinance).filter(x=>x.ordinanceName),
    c.articles
  );
}

function page(body,title='GOV:IMPACT'){
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><link rel="stylesheet" href="/style.css"></head><body>
  <header class="mast"><div class="brand"><span>GOV:IMPACT</span><h1>법령·제도 변경 행정영향 레이더</h1><p>법이 바뀌면, 우리 행정에서 무엇을 확인해야 하는지 먼저 찾습니다.</p></div><div class="trust"><b>광주광역시 서구</b><span>공식 연계데이터 우선 · AI 판단 없음</span></div></header>
  <main class="wrap">
  <section class="hero card"><div><span class="kicker">AIBLE 지방행정 실험</span><h2>법령 개정 사실을 <em>“우리 업무의 할 일”</em>로 바꿉니다.</h2><p>법제처 변경이력과 법령↔자치법규 연계정보를 대조해 검토 후보를 표시합니다.</p></div><div class="flow"><div>법령 개정</div><i>→</i><div>공식 연계</div><i>→</i><div>영향 후보</div><i>→</i><div>담당자 검토</div></div></section>
  <section class="toolbar card"><form class="datebox" action="/api/view"><label>변경일</label><input name="date" type="date" required><button class="primary">변경 법령 조회</button></form><form class="searchbox" action="/api/view"><label>법령 직접 검색</label><div><input name="q" placeholder="예: 아동복지법"><button id="searchLaw">검색</button></div></form></section>
  ${body}
  </main><footer>Developed by 광주광역시 서구 펀온워크 AIBLE · GOV:IMPACT MVP</footer></body></html>`;
}

function lawsHtml(laws,date){
  if(!laws.length) return '<section class="card right"><div class="empty">조회된 법령이 없습니다.</div></section>';
  const cards=laws.map(x=>{
    const href='/api/view?date='+encodeURIComponent(date||'')+'&lawId='+encodeURIComponent(x.lawId||'')+'&lawName='+encodeURIComponent(x.lawName||'');
    return `<a class="law-item" href="${href}" style="display:block;text-decoration:none;color:inherit"><div class="topline"><span class="mini">${esc(x.changeType||'변경')}</span><span class="mini">${esc(x.lawType||'법령')}</span></div><h4>${esc(x.lawName)}</h4><p>${esc(x.ministry||'-')} · 시행 ${fmt(x.effectiveDate)}</p></a>`;
  }).join('');
  return `<section class="card left" style="margin-top:16px"><div class="section-head"><div><span class="eyebrow">STEP 1</span><h3>법령 목록</h3></div><span class="count">${laws.length}건</span></div><div class="law-list">${cards}</div></section>`;
}

function impactHtml(data){
  const ord=(data.ordinances||[]).map(x=>`<article class="ord-card"><h4>${esc(x.ordinanceName)}</h4><p>${esc(x.reason||'')}</p><span class="match ${x.matchType==='official-linkage'?'official':'body'}">${x.matchType==='official-linkage'?'공식 연계':'본문 언급'}</span></article>`).join('') || '<div class="muted">연계 자치법규 후보를 찾지 못했습니다. 영향 없음으로 확정하는 결과는 아닙니다.</div>';
  const arts=(data.changedArticles||[]).map(x=>`<article class="article-card"><h4>${esc(x.articleInfo||x.articleNo||'변경 조문')}</h4><p>개정 ${fmt(x.articleChangeDate)} · 시행 ${fmt(x.articleEffectiveDate)}</p></article>`).join('') || '<div class="muted">선택 날짜 기준 별도 조문정보가 확인되지 않았습니다.</div>';
  const actions=(data.actions||[]).map((x,i)=>`<label><input type="checkbox"><span><b>${String(i+1).padStart(2,'0')}.</b> ${esc(x)}</span></label>`).join('');
  return `<section class="card right" style="margin-top:16px"><div class="impact-title"><div><span class="impact-badge">검토 후보</span><h2>${esc(data.change?.lawName||'')}</h2><p>${esc(data.change?.changeType||'변경')} · 시행 ${fmt(data.change?.effectiveDate)}</p></div></div><div class="metrics"><div><b>${data.ordinances?.length||0}</b><span>연계 자치법규</span></div><div><b>${data.changedArticles?.length||0}</b><span>변경 조문</span></div><div><b>${fmt(data.change?.effectiveDate)}</b><span>시행일</span></div></div><div class="block"><div class="block-title"><span>01</span><h3>서구 자치법규 영향 후보</h3></div>${ord}</div><div class="block"><div class="block-title"><span>02</span><h3>확인된 변경 조문</h3></div>${arts}</div><div class="block"><div class="block-title"><span>03</span><h3>행정 조치 체크리스트</h3></div><div class="checklist">${actions}</div></div><div class="caution"><b>중요</b> 법적 판단 결과가 아니라 검토 대상 후보입니다. 원문과 소관부서 검토를 거쳐 확정하세요.</div></section>`;
}

export default async function handler(req,res){
  res.setHeader('Content-Type','text/html; charset=utf-8');
  try{
    if(!OC){
      res.statusCode=200;
      return res.end(page('<section class="setup card"><b>법제처 API 인증값 설정이 필요합니다.</b><p class="muted">Vercel 환경변수 LAW_OC를 등록하면 실시간 조회가 시작됩니다. 기본 기관코드는 광주 서구 3600000입니다.</p></section>'));
    }
    const u=new URL(req.url,'https://local.invalid');
    const date=date8(u.searchParams.get('date')||'');
    const q=(u.searchParams.get('q')||'').trim();
    const lawId=u.searchParams.get('lawId')||'';
    const lawName=u.searchParams.get('lawName')||'';

    if(lawName||lawId){
      const data=await impact(lawId,lawName,date);
      return res.end(page(impactHtml(data),lawName||'GOV:IMPACT'));
    }
    if(q){
      const laws=await search(q);
      return res.end(page(lawsHtml(laws,''),'법령 검색'));
    }
    if(date){
      const data=await changes(date);
      return res.end(page(lawsHtml(data.laws,date),'변경 법령'));
    }
    return res.end(page('<section class="card how"><span class="eyebrow">START</span><h3>변경일을 선택하거나 법령을 검색하세요.</h3><p>공식 연계정보를 먼저 대조하고, 결과는 담당자 검토 후보로만 제공합니다.</p></section>'));
  }catch(e){
    res.statusCode=500;
    return res.end(page('<section class="setup card"><b>조회 중 오류가 발생했습니다.</b><p class="error">'+esc(e.message)+'</p></section>'));
  }
}
