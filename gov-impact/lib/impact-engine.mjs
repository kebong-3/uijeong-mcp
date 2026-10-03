export const normalizeLawName = (name='') => String(name).replace(/\s+/g, '').replace(/[「」『』\[\]()]/g, '').trim();

export function deepFindRecords(node, signatures=[]) {
  const out = [];
  const visit = (v) => {
    if (!v || typeof v !== 'object') return;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item && typeof item === 'object' && signatures.some(k => Object.prototype.hasOwnProperty.call(item, k))) out.push(item);
        else visit(item);
      }
      return;
    }
    if (signatures.some(k => Object.prototype.hasOwnProperty.call(v, k))) out.push(v);
    for (const child of Object.values(v)) visit(child);
  };
  visit(node);
  const seen = new Set();
  return out.filter(item => {
    const key = JSON.stringify(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function pick(item, keys, fallback='') {
  for (const key of keys) {
    if (item?.[key] !== undefined && item?.[key] !== null && item?.[key] !== '') return item[key];
  }
  return fallback;
}

export function normalizeLawChange(item={}) {
  return {
    lawId: String(pick(item, ['법령ID','법령아이디','ID','id'])),
    masterId: String(pick(item, ['법령일련번호','법령마스터번호','MST'])),
    lawName: String(pick(item, ['법령명한글','법령명','법령명_한글'])),
    ministry: String(pick(item, ['소관부처명','소관부처'])),
    lawType: String(pick(item, ['법령구분명','법령종류'])),
    changeType: String(pick(item, ['제개정구분명','제개정구분'])),
    promulgationDate: String(pick(item, ['공포일자'])),
    effectiveDate: String(pick(item, ['시행일자']))
  };
}

export function normalizeArticleChange(item={}) {
  return {
    lawId: String(pick(item, ['법령ID','ID'])),
    lawName: String(pick(item, ['법령명한글','법령명'])),
    articleNo: String(pick(item, ['조문번호'])),
    articleInfo: String(pick(item, ['조문정보','조문내용'])),
    reason: String(pick(item, ['변경사유'])),
    articleChangeDate: String(pick(item, ['조문개정일','조문제개정일'])),
    articleEffectiveDate: String(pick(item, ['조문시행일']))
  };
}

export function normalizeLocalLink(item={}) {
  return {
    ordinanceId: String(pick(item, ['자치법규ID'])),
    ordinanceName: String(pick(item, ['자치법규명'])),
    ordinanceType: String(pick(item, ['자치법규종류'])),
    lawId: String(pick(item, ['법령ID'])),
    lawName: String(pick(item, ['법령명한글','법령명']))
  };
}

export function normalizeOrdinance(item={}) {
  return {
    ordinanceId: String(pick(item, ['자치법규ID'])),
    ordinanceName: String(pick(item, ['자치법규명'])),
    ordinanceType: String(pick(item, ['자치법규종류'])),
    agencyName: String(pick(item, ['지자체기관명'])),
    effectiveDate: String(pick(item, ['시행일자']))
  };
}

export function buildImpact(change, localLinks=[], bodyHits=[], articles=[]) {
  const id = String(change.lawId || '');
  const name = normalizeLawName(change.lawName);
  const exact = localLinks.filter(x => (id && String(x.lawId) === id) || (name && normalizeLawName(x.lawName) === name));
  const merged = new Map();
  for (const x of exact) {
    const key = x.ordinanceId || x.ordinanceName;
    merged.set(key, {...x, matchType:'official-linkage', score:100, reason:'법제처 법령-자치법규 공식 연계정보 일치'});
  }
  for (const x of bodyHits) {
    const key = x.ordinanceId || x.ordinanceName;
    if (!merged.has(key)) merged.set(key, {...x, matchType:'body-mention', score:70, reason:'자치법규 본문에 법령명 언급'});
  }
  const ordinances = [...merged.values()].sort((a,b)=>(b.score||0)-(a.score||0));
  const changedArticles = articles.filter(a => (!id || String(a.lawId)===id) || normalizeLawName(a.lawName)===name);
  const actions = ordinances.length
    ? ['상위법 개정 조문과 연계 자치법규 조문 대조','조례·규칙 개정 필요 여부 검토','시행일 이전 정비 일정 확인']
    : ['공식 연계가 없더라도 소관 업무·지침 영향 여부 확인'];
  actions.push('관련 사업계획·업무편람·신청서·서식의 인용 법령 확인');
  actions.push('홈페이지·민원안내·FAQ의 법령명 및 기준 확인');
  actions.push('예산·위탁·위원회·지원대상 기준 변화 여부 확인');
  return {
    change,
    impactFound: ordinances.length > 0,
    impactLevel: ordinances.length >= 3 ? 'high' : ordinances.length ? 'medium' : 'watch',
    ordinances,
    changedArticles,
    actions
  };
}
