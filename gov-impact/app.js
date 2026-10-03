const $ = s => document.querySelector(s);
let currentDate = '';
let selectedLaw = null;

const todayKST = new Date(Date.now()+9*3600*1000);
const yesterday = new Date(todayKST.getTime()-86400000);
$('#changeDate').value = yesterday.toISOString().slice(0,10);

function ymd(v){ return (v||'').replaceAll('-',''); }
function fmt(v=''){ const s=String(v).replace(/\D/g,''); return s.length===8?`${s.slice(0,4)}.${s.slice(4,6)}.${s.slice(6,8)}`:(v||'-'); }
function esc(v=''){ return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function dday(v=''){ const s=String(v).replace(/\D/g,''); if(s.length!==8)return '-'; const t=new Date(`${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}T00:00:00+09:00`); const now=new Date(); const d=Math.ceil((t-now)/86400000); return d>0?`D-${d}`:d===0?'D-DAY':`시행 ${Math.abs(d)}일`; }

async function api(params){ const q=new URLSearchParams(params); const r=await fetch(`/api/law?${q}`); const data=await r.json().catch(()=>({ok:false,message:'응답 해석 실패'})); if(!r.ok||!data.ok) throw Object.assign(new Error(data.message||'조회 실패'),{data,status:r.status}); return data; }

async function checkStatus(){
  try{ const s=await api({mode:'status'}); if(!s.configured){ showSetup(); } }
  catch{}
}
function showSetup(){
  const el=$('#setupBanner'); el.classList.remove('hidden'); el.innerHTML=`<b>법제처 API 인증값 설정이 필요합니다.</b><br><span class="muted">Vercel → Project Settings → Environment Variables에 <code>LAW_OC</code>를 추가하면 실시간 조회가 시작됩니다. 기관코드는 기본값으로 광주광역시 서구(3600000)가 설정돼 있습니다.</span>`;
}

function renderLaws(laws=[]){
  $('#changeCount').textContent=`${laws.length}건`;
  const el=$('#changeList');
  if(!laws.length){ el.innerHTML='<div class="empty">해당 날짜에 조회된 변경 법령이 없습니다.</div>'; return; }
  el.innerHTML=laws.map((x,i)=>`<article class="law-item" data-i="${i}"><div class="topline"><span class="mini">${esc(x.changeType||'변경')}</span><span class="mini">${esc(x.lawType||'법령')}</span></div><h4>${esc(x.lawName)}</h4><p>${esc(x.ministry||'-')} · 공포 ${fmt(x.promulgationDate)} · 시행 ${fmt(x.effectiveDate)}</p></article>`).join('');
  [...el.querySelectorAll('.law-item')].forEach(n=>n.addEventListener('click',()=>selectLaw(laws[Number(n.dataset.i)],n)));
}

async function loadChanges(){
  currentDate=ymd($('#changeDate').value); if(!currentDate)return;
  $('#changeList').innerHTML='<div class="loading">법령 변경이력을 조회하고 있습니다…</div>';
  try{ const d=await api({mode:'changes',date:currentDate}); renderLaws(d.laws||[]); if(d.partial) alert('조회량이 많아 일부 데이터만 표시될 수 있습니다.'); }
  catch(e){ if(e.data?.code==='LAW_OC_NOT_CONFIGURED') showSetup(); $('#changeList').innerHTML=`<div class="empty error">${esc(e.message)}</div>`; }
}

async function selectLaw(law,node){
  selectedLaw=law; document.querySelectorAll('.law-item').forEach(x=>x.classList.remove('active')); node?.classList.add('active');
  $('#impactEmpty').classList.add('hidden'); $('#impactView').classList.remove('hidden');
  $('#impactLawName').textContent=law.lawName; $('#impactMeta').textContent=`${law.ministry||'-'} · ${law.changeType||'변경'} · 시행 ${fmt(law.effectiveDate)}`;
  $('#ordinanceList').innerHTML='<div class="loading">서구 자치법규 연계정보를 대조하고 있습니다…</div>'; $('#articleList').innerHTML='<div class="loading">변경 조문 확인 중…</div>'; $('#actionList').innerHTML='';
  try{
    const d=await api({mode:'impact',lawId:law.lawId||'',lawName:law.lawName||'',date:currentDate}); renderImpact(d);
  }catch(e){ if(e.data?.code==='LAW_OC_NOT_CONFIGURED') showSetup(); $('#ordinanceList').innerHTML=`<div class="error">${esc(e.message)}</div>`; }
}

function renderImpact(d){
  const level={high:'영향 후보 다수',medium:'연계 확인',watch:'추가 확인'}[d.impactLevel]||'검토'; $('#impactBadge').textContent=level;
  $('#ordCount').textContent=d.ordinances?.length||0; $('#articleCount').textContent=d.changedArticles?.length||0; $('#dday').textContent=dday(d.change?.effectiveDate);
  const ord=$('#ordinanceList');
  ord.innerHTML=d.ordinances?.length ? d.ordinances.map(x=>`<article class="ord-card"><h4>${esc(x.ordinanceName)}</h4><p>${esc(x.ordinanceType||'자치법규')}${x.matchType==='body-mention' && x.effectiveDate ? ` · 자치법규 시행 ${fmt(x.effectiveDate)}` : ''}</p><span class="match ${x.matchType==='official-linkage'?'official':'body'}">${x.matchType==='official-linkage'?'공식 연계':'본문 언급'}</span><p>${esc(x.reason||'')}</p></article>`).join('') : '<div class="muted">법제처 공식 연계정보 및 법령명 본문검색에서 서구 자치법규 후보를 찾지 못했습니다. 영향 없음으로 확정하는 결과는 아닙니다.</div>';
  const art=$('#articleList');
  art.innerHTML=d.changedArticles?.length ? d.changedArticles.map(x=>`<article class="article-card"><h4>${esc(x.articleInfo||x.articleNo||'변경 조문')}</h4><p>조문 ${esc(x.articleNo||'-')} · 개정 ${fmt(x.articleChangeDate)} · 시행 ${fmt(x.articleEffectiveDate)}</p>${x.reason?`<p><b>변경사유:</b> ${esc(x.reason)}</p>`:''}</article>`).join('') : '<div class="muted">선택한 변경일 기준 조문 변경이력에서 별도 조문 정보가 확인되지 않았습니다.</div>';
  $('#actionList').innerHTML=(d.actions||[]).map((x,i)=>`<label><input type="checkbox"/><span><b>${String(i+1).padStart(2,'0')}.</b> ${esc(x)}</span></label>`).join('');
}

async function searchLaw(){
  const q=$('#lawQuery').value.trim(); if(q.length<2)return alert('검색어를 2자 이상 입력해주세요.');
  $('#changeList').innerHTML='<div class="loading">법령을 검색하고 있습니다…</div>';
  try{ const d=await api({mode:'search',q}); currentDate=''; renderLaws(d.laws||[]); }
  catch(e){ if(e.data?.code==='LAW_OC_NOT_CONFIGURED') showSetup(); $('#changeList').innerHTML=`<div class="empty error">${esc(e.message)}</div>`; }
}

$('#loadChanges').addEventListener('click',loadChanges); $('#searchLaw').addEventListener('click',searchLaw); $('#lawQuery').addEventListener('keydown',e=>{if(e.key==='Enter')searchLaw();}); $('#printBtn').addEventListener('click',()=>window.print());
checkStatus();
