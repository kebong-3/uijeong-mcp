import assert from 'node:assert/strict';
import worker from '../worker/index.js';
const endpoint='https://test.invalid/mcp';let count=0;
async function send(method,params={},env={},auth=true){const req=new Request(endpoint,{method:'POST',headers:{'content-type':'application/json',...(auth?{'oai-authenticated-user-id':'test-user'}:{})},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});const res=await worker.fetch(req,env);const body=await res.json();return {res,body};}
async function call(name,args={},env={}){const {body}=await send('tools/call',{name,arguments:args},env);assert(!body.error);return {data:JSON.parse(body.result.content[0].text),error:body.result.isError};}
const init=await send('initialize',{protocolVersion:'2025-06-18'}, {},false);assert.equal(init.body.result.protocolVersion,'2025-06-18');count++;
const list=await send('tools/list',{}, {},false);assert.equal(list.body.result.tools.length,14);count++;
const unauth=await send('tools/call',{name:'council_status'}, {},false);assert.equal(unauth.res.status,401);count++;
for(const path of ['/','/guide','/sources','/support','/privacy','/terms']){const res=await worker.fetch(new Request('https://test.invalid'+path));assert.equal(res.status,200);assert((await res.text()).includes('<html lang="ko">'));count++;}
const cost=await call('budget_calculate',{operation:'cost',arguments:{items:[{unit_price:'20800',quantity:100,times:2}]}});assert.equal(cost.data.total_won,'4160000');count++;
const big=await call('budget_calculate',{operation:'cost',arguments:{items:[{unit_price:'999999999999999999',quantity:2}]}});assert.equal(big.data.total_won,'1999999999999999998');count++;
const funding=await call('budget_calculate',{operation:'matching_funds',arguments:{total:'4160000',rates:{national:'50',municipal:'50'}}});assert.equal(funding.data.shares[0].amount_won,'2080000');count++;
const zero=await call('budget_calculate',{operation:'change',arguments:{before:'0',after:'100'}});assert.equal(zero.data.change_rate_pct,null);count++;
const bad=await call('budget_calculate',{operation:'matching_funds',arguments:{total:'100',rates:{a:'60',b:'50'}}});assert.equal(bad.error,true);count++;
const missing=await call('council_search_minutes',{keyword:'체납관리단',council_id:'062006'});assert.equal(missing.data.status,'NOT_CONFIGURED');assert.equal(missing.error,true);count++;
const council=await call('council_find_council',{query:'광주 서구'});assert(council.data.items.some(x=>x.council_id==='062006'));count++;
const plan=await call('local_workflow_plan',{question:'사업 의회 예산 조례 검토',jurisdiction:'광주 서구',fiscal_year:2027});assert.equal(plan.data.status,'PLAN_ONLY');count++;
const realFetch=globalThis.fetch;let seen=[];
globalThis.fetch=async(url,options)=>{assert.equal(options.redirect,"manual");seen.push(String(url));const u=new URL(url);if(u.hostname==='uijeong-mcp.onrender.com')throw Error('Render should not be used');if(u.pathname.endsWith('minutes.do'))return new Response(JSON.stringify(u.searchParams.get('displayType')==='detail'?{DOCID:'D1',CONTENT:'공개 회의록 본문'}:[{RESULT_CODE:'SUCCESS',TOTAL_COUNT:1,LIST:[{ROW:{DOCID:'D1',MTG_DE:'20260101',MTGNM:'위원회'}}]}]));if(u.pathname.endsWith('lawSearch.do'))return new Response(JSON.stringify({OrdinSearch:{totalCnt:1,ordin:[{자치법규일련번호:'123',자치법규명:'시험 조례',시행일자:'20260101'}]}}));if(u.pathname.endsWith('lawService.do'))return new Response(JSON.stringify({자치법규:{조문:'공개 조문',시행일자:'20260101'}}));return new Response(JSON.stringify({QWGJK:[{head:[{RESULT:{CODE:'INFO-000'}}]},{row:[{dbiz_nm:'사업',amount:100}]}]}));};
for(const [n,a,e]of [['council_search_minutes',{keyword:'주제',council_id:'062006'},{CLIK_API_KEY:'secret-test'}],['council_read_source',{docid:'D1'},{CLIK_API_KEY:'secret-test'}],['ordinance_search',{query:'마을관리'},{LAW_OC:'private-oc'}],['ordinance_get_document',{kind:'ordinance',document_id:'123'},{LAW_OC:'private-oc'}],['budget_fetch_api',{api_id:'lofin_projects',params:{fyr:'2026',exe_ymd:'20260101'}},{LOFIN_API_KEY:'secret-budget'}]]){const r=await call(n,a,e);assert.equal(r.error,false);assert(!JSON.stringify(r.data).includes('secret-test'));count++;}
assert(seen.every(u=>!u.includes('onrender.com')));count++;
const reject=await call('budget_fetch_api',{api_id:'lofin_projects',params:{fyr:'2026',exe_ymd:'20260101',url:'https://evil.invalid'}},{LOFIN_API_KEY:'secret'});assert.equal(reject.error,true);count++;
globalThis.fetch=async()=>new Response(JSON.stringify({echo:'secret-test',CODE:'ERROR01'}));const error=await call('council_search_minutes',{keyword:'주제',council_id:'062006'},{CLIK_API_KEY:'secret-test'});assert.equal(error.error,true);assert(!JSON.stringify(error).includes('secret-test'));count++;
globalThis.fetch=async()=>new Response('not-json');const malformed=await call('ordinance_search',{query:'조례'},{LAW_OC:'secret'});assert.equal(malformed.error,true);count++;
globalThis.fetch=realFetch;
console.log(JSON.stringify({status:'PASS',checks:count,tools:14,live_credentials_tested:false}));
