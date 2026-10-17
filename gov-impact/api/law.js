import {
  deepFindRecords,
  normalizeLawChange,
  normalizeArticleChange,
  normalizeLocalLink,
  normalizeOrdinance,
  buildImpact
} from '../lib/impact-engine.mjs';

const BASE = 'https://www.law.go.kr/DRF/lawSearch.do';
const AGENCY = process.env.AGENCY_CODE || '3600000';
const PARENT = process.env.PARENT_AGENCY_CODE || '6290000';
const OC = process.env.LAW_OC || '';
let linkCache = { at: 0, value: null };

function json(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type','application/json; charset=utf-8');
  res.setHeader('Cache-Control','s-maxage=900, stale-while-revalidate=3600');
  res.end(JSON.stringify(body));
}

function validDate(v) { return /^20\d{6}$/.test(String(v||'')); }

async function lawFetch(params) {
  if (!OC) throw new Error('LAW_OC_NOT_CONFIGURED');
  const url = new URL(BASE);
  const all = { OC, type:'JSON', ...params };
  for (const [k,v] of Object.entries(all)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
  const r = await fetch(url, { headers:{'User-Agent':'GOV-IMPACT/0.1'} });
  if (!r.ok) throw new Error(`LAW_API_${r.status}`);
  const text = await r.text();
  try { return JSON.parse(text); }
  catch { throw new Error('LAW_API_INVALID_JSON'); }
}

function getTotal(data) {
  const candidates = [];
  const walk = v => {
    if (!v || typeof v !== 'object') return;
    if (!Array.isArray(v)) {
      for (const [k,x] of Object.entries(v)) {
        if (/totalCnt|totalcnt|검색건수|검색결과개수/i.test(k) && !Number.isNaN(Number(x))) candidates.push(Number(x));
        walk(x);
      }
    } else v.forEach(walk);
  };
  walk(data); return candidates.length ? Math.max(...candidates) : 0;
}

async function fetchPaged(params, signatures, maxPages=12) {
  const display = 100;
  const first = await lawFetch({...params, display, page:1});
  let rows = deepFindRecords(first, signatures);
  const total = getTotal(first);
  const pages = Math.min(maxPages, Math.max(1, Math.ceil(total/display)));
  if (pages > 1) {
    const rest = await Promise.all(Array.from({length:pages-1},(_,i)=>lawFetch({...params,display,page:i+2})));
    for (const data of rest) rows.push(...deepFindRecords(data, signatures));
  }
  return {rows,total,pages,partial: total > pages*display};
}

async function getChanges(date) {
  const [laws, articles] = await Promise.all([
    fetchPaged({target:'lsHstInf', regDt:date}, ['법령명한글','법령ID','법령일련번호'], 8),
    fetchPaged({target:'lsJoHstInf', regDt:date}, ['조문번호','조문정보','조문개정일'], 10)
  ]);
  const lawRows = laws.rows.map(normalizeLawChange).filter(x=>x.lawName);
  const articleRows = articles.rows.map(normalizeArticleChange).filter(x=>x.lawName || x.lawId);
  return { laws:lawRows, articles:articleRows, total:laws.total, partial:laws.partial || articles.partial };
}

async function getLocalLinks() {
  const now = Date.now();
  if (linkCache.value && now - linkCache.at < 6*3600*1000) return linkCache.value;
  const r = await fetchPaged({target:'lnkOrg', org:AGENCY}, ['자치법규명','법령명한글','법령ID'], 15);
  const value = {rows:r.rows.map(normalizeLocalLink).filter(x=>x.ordinanceName), total:r.total, partial:r.partial};
  linkCache = {at:now, value};
  return value;
}

async function getBodyHits(lawName) {
  if (!lawName) return [];
  const r = await fetchPaged({target:'ordin', nw:1, search:2, query:lawName, org:PARENT, sborg:AGENCY}, ['자치법규명','지자체기관명','자치법규ID'], 3);
  return r.rows.map(normalizeOrdinance).filter(x=>x.ordinanceName);
}

async function searchLaw(query) {
  const r = await fetchPaged({target:'law', search:1, query, nw:1, sort:'ddes'}, ['법령명한글','법령ID','법령일련번호'], 2);
  return r.rows.map(normalizeLawChange).filter(x=>x.lawName);
}

export default async function handler(req,res) {
  try {
    const url = new URL(req.url, 'https://local.invalid');
    const mode = url.searchParams.get('mode') || 'status';
    if (mode === 'status') return json(res,200,{ok:true, configured:Boolean(OC), agencyCode:AGENCY, parentAgencyCode:PARENT});

    if (!OC) return json(res,503,{ok:false, code:'LAW_OC_NOT_CONFIGURED', message:'Vercel 환경변수 LAW_OC에 법제처 OPEN API 인증값을 등록하세요.'});

    if (mode === 'changes') {
      const date = url.searchParams.get('date');
      if (!validDate(date)) return json(res,400,{ok:false,message:'date는 YYYYMMDD 형식이어야 합니다.'});
      const data = await getChanges(date);
      return json(res,200,{ok:true,date,...data});
    }

    if (mode === 'impact') {
      const lawId = url.searchParams.get('lawId') || '';
      const lawName = url.searchParams.get('lawName') || '';
      const date = url.searchParams.get('date') || '';
      if (!lawId && !lawName) return json(res,400,{ok:false,message:'lawId 또는 lawName이 필요합니다.'});
      const [links, bodyHits, changeData] = await Promise.all([
        getLocalLinks(),
        getBodyHits(lawName),
        validDate(date) ? getChanges(date) : Promise.resolve({laws:[],articles:[]})
      ]);
      let change = changeData.laws.find(x => (lawId && x.lawId===lawId) || (lawName && x.lawName===lawName));
      if (!change) change = {lawId, lawName, ministry:'', lawType:'', changeType:'', promulgationDate:'', effectiveDate:''};
      const result = buildImpact(change, links.rows, bodyHits, changeData.articles);
      return json(res,200,{ok:true, agencyCode:AGENCY, linkageTotal:links.total, linkagePartial:links.partial, ...result});
    }

    if (mode === 'search') {
      const query = (url.searchParams.get('q')||'').trim();
      if (query.length < 2) return json(res,400,{ok:false,message:'검색어를 2자 이상 입력하세요.'});
      const laws = await searchLaw(query);
      return json(res,200,{ok:true,laws:laws.slice(0,50)});
    }

    return json(res,404,{ok:false,message:'지원하지 않는 mode입니다.'});
  } catch (e) {
    const code = e?.message || 'UNKNOWN_ERROR';
    return json(res,500,{ok:false,code,message: code==='LAW_OC_NOT_CONFIGURED' ? 'LAW_OC 환경변수가 필요합니다.' : '법령정보 조회 중 오류가 발생했습니다.'});
  }
}
