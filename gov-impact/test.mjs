import { buildImpact, normalizeLawChange, normalizeLocalLink, deepFindRecords } from './lib/impact-engine.mjs';
const raw={root:{law:[{'법령ID':'123','법령명한글':'아동복지법','제개정구분명':'일부개정'}]}};
const rows=deepFindRecords(raw,['법령명한글']);
if(rows.length!==1) throw new Error('deepFindRecords failed');
const change=normalizeLawChange(rows[0]);
const link=normalizeLocalLink({'법령ID':'123','법령명한글':'아동복지법','자치법규ID':'A1','자치법규명':'광주광역시 서구 아동복지 지원 조례'});
const impact=buildImpact(change,[link],[],[]);
if(!impact.impactFound || impact.ordinances.length!==1 || impact.ordinances[0].score!==100) throw new Error('impact match failed');
console.log('tests ok');
