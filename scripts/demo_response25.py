#!/usr/bin/env python3
"""Generate a deterministic SYNTHETIC demo. No network or runtime secret needed."""
from pathlib import Path
import sys,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import evidence_core as E
import response_core as Q

def main():
    root=Path(__file__).resolve().parents[1]/'docs/examples-v250';root.mkdir(exist_ok=True)
    raw='<b>○가상위원 위원</b>합성사업 확대와 예산 산출근거를 설명해 주십시오.<br><b>○가상복지과장 가상인</b>예산이 확보되면 확대를 검토하겠습니다.<br>'
    record=E.make_record({'DOCID':'SYNTHETIC-DEMO','RASMBLY_ID':'062006','MTG_DE':'20250101','MTGNM':'합성위원회'},
        E.parse_turns(raw),source='SYNTHETIC',source_kind='SYNTHETIC')
    payload={'status':'COMPLETE','items':E.record_events(record,'합성사업','질의답변'),
        'followup_items':E.record_events(record,'합성사업','약속'),'coverage':[]}
    facts=[dict(id='F1',text='합성사업의 2026년 최종예산은 120000천원입니다.',as_of='2026-09-01',
                fiscal_year=2026,unit='천원',document_ref='합성 예산서 12쪽')]
    pack=Q.build_response(payload,'SYNTHETIC-NOT-A-LIVE-SNAPSHOT','합성사업','가상복지과','예산심사',facts,'2026-09-20')
    wrong='합성사업의 2026년 최종예산은 200000천원입니다. 확대가 완료되었습니다.'
    claims=[dict(text=wrong.split('. ')[0]+'.',citation_id='F:F1',support_excerpt=facts[0]['text'])]
    audit=Q.audit_claims(wrong,claims,[],facts,'2026-09-20')
    base=dict(metric='합성사업 예산',entity='합성기관',population='사업 전체',period_basis='연간',accounting_basis='최종예산',document_ref='합성 예산서')
    figures=Q.compare_metrics([dict(name='합성 예산',previous=dict(base,value='1',unit='억원',fiscal_year=2025),
        current=dict(base,value='120000',unit='천원',fiscal_year=2026))])
    result={'source_kind':'SYNTHETIC','not_real_seogu_facts':True,'response_pack':pack,'intentionally_wrong_draft_audit':audit,'unit_comparison':figures}
    (root/'synthetic-demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (root/'실행예시_합성자료.md').write_text('# 실행예시 — 모든 인물·회의·수치는 합성자료\n\n실제 서구 사업의 예산·발언·성과가 아닙니다. 스냅샷 식별자도 실서비스에서 사용할 수 없습니다.\n\n'+pack['plain_text']+'\n\n## 잘못된 초안 검수 예시\n\n초안: '+wrong+'\n\n- 제공자료의 120000천원과 초안의 200000천원 불일치: NUMBERS_NOT_IN_EXCERPT\n- “확대가 완료되었습니다”는 인용 연결 미확인 구간으로 표시\n- 1억원→120000천원 비교: 20000000원 증가, 20.00% 증가\n- 원문 근거가 있어도 의미상 입증과 제출 승인은 담당자가 확인\n')
    print(json.dumps({'generated':[str(root/'synthetic-demo.json'),str(root/'실행예시_합성자료.md')]}))
if __name__=='__main__':main()
