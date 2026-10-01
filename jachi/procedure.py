"""Input-based legislative dependency screening; never issues legal clearance.

No news-to-law conversion, automatic publication, or caller-controlled verification.
Dates supplied by a caller remain assertions, even if accompanied by official URLs.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field

LAW = 'https://www.law.go.kr/lsInfoP.do?lsId=001656'
ADMIN = 'https://www.law.go.kr/법령/행정절차법'
DECREE = 'https://www.law.go.kr/법령/지방자치법시행령'
GUIDE = 'https://www.moleg.go.kr/board.es?act=view&bid=0007&list_no=138536&mid=a10404000000'


class ProcedureInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    jurisdiction: str = Field(min_length=2, max_length=120)
    instrument: Literal['ordinance', 'rule'] = 'rule'
    action: Literal['prepare', 'submit', 'promulgate', 'implement', 'remediate'] = 'prepare'
    basis_kind: Literal['ordinance_amendment', 'current_ordinance', 'law', 'unknown'] = 'unknown'
    basis_title: str = Field(default='', max_length=300)
    basis_article: str = Field(default='', max_length=80)
    # Basis ID is compared only with documents actually retrieved during a review.
    basis_document_id: str = Field(default='', pattern=r'^\d*$', max_length=24)
    ordinance_stage: Literal['unknown', 'draft', 'submitted', 'committee_passed',
        'council_passed', 'promulgated', 'effective', 'reconsideration', 'rejected', 'withdrawn'] = 'unknown'
    dates: dict[Literal['ordinance_submission', 'ordinance_vote', 'ordinance_transmission',
        'ordinance_promulgation', 'basis_effective', 'rule_promulgation', 'rule_effective',
        'implementation', 'notice_start', 'notice_end'], date] = Field(default_factory=dict, max_length=10)
    # Dates can be future/planned; a vote date alone never proves a completed vote.
    source_urls: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=6)
    final_text_matches: Literal['unknown', 'yes', 'no'] = 'unknown'
    steps: dict[Literal['law_review', 'notice', 'regulatory_review', 'cost_estimate',
        'gender_review', 'corruption_review', 'social_security_consultation',
        'ordinance_rule_committee', 'prior_report', 'gazette', 'system_forms',
        'transition', 'budget'], Literal['unknown', 'pending', 'done', 'not_applicable']] = Field(default_factory=dict, max_length=13)
    exception_reason: str = Field(default='', max_length=1000)


def procedure_guide() -> dict:
    return {
        'purpose': '조례·규칙 입안부터 시행까지의 순서·근거·증빙 누락 점검',
        'ordinance_sequence': ['입안·관계부서 협의', '적용되는 예고·평가·비용추계',
            '법무심사·조례규칙심의 등 해당 절차', '의회 제출·상임위 심사',
            '본회의 의결·의결문 확인', '이송·재의 여부 확인', '공포·통지', '부칙에 따른 시행'],
        'rule_sequence': ['현행 법률/조례 또는 개정 의존 근거 구분', '안 작성·관계부서 협의',
            '적용되는 예고·평가·법무심사', '해당 심의·사전보고 등',
            '개정 의존 조례의 의결 최종문·공포·시행일 재대조', '규칙 공포·시행일 확인',
            '요금·신청·지원·시스템·서식 적용'],
        'rules': [
            '규칙 전체를 의회 의결 대상으로 취급하지 않습니다. 현행 법령 또는 조례 범위의 규칙인지 확인합니다.',
            '입법예고·초안·내부 협의는 병행 가능하나 개정안 통과를 전제로 한 공포·집행과 구분합니다.',
            '상임위 통과·결재 완료·예정 의결일은 본회의 의결 또는 조례 공포·시행의 증거가 아닙니다.',
            '공포일과 시행일은 다릅니다. 지방자치법 제32조 제8항과 해당 부칙·조문별 시행일을 확인합니다.',
            '의회 수정의결·부결·철회·재의 시 규칙안의 조문·별표·요금·서식·부칙을 다시 대조합니다.',
            '일반 법정기간을 모든 사건에 자동 적용하지 않습니다. 제출주체·예외·우리 입법절차 법규를 확인합니다.',
            '이미 공포·집행했다면 추가 적용 보류 검토, 법무 보고, 영향 목록·정비절차 검토를 먼저 합니다. 자동 무효·소급치유·환급을 단정하지 않습니다.'
        ],
        'approval_handoff': [
            {'role': '담당자·팀장', 'check': '근거 조문·의안번호·진행상태·날짜·규칙 대응표와 증빙 확보'},
            {'role': '과장·법무담당', 'check': '최종 의결문·부칙·현행 위임범위·적용 예외와 법무심사 대조'},
            {'role': '국장·부단체장', 'check': '예산·시스템·관련부서 영향 및 미완료 선행절차 확인'},
            {'role': '최종 결재·공포 담당', 'check': '의결·공포 증빙 원문과 실제 시행일 재확인. 결재 완료만으로 발령하지 않음'}
        ],
        'needed_evidence': ['현행 상위법·조례 원문과 위임 조문', '의안번호·본회의 의결 최종문',
            '이송·재의 여부', '공보 공포번호·공포일', '부칙·조문별 시행일',
            '규칙안·별표·서식의 신구 대비', '예고·심의·협의·사전보고 적용 여부와 증빙'],
        'source_links': [
            {'url': url, 'label': label, 'kind': 'OFFICIAL_REFERENCE', 'status': 'REFERENCE_PROVIDED',
             'direct_document': False, 'markdown': f'[{label}]({url})'}
            for url, label in [(LAW, '지방자치법 제28·29·32조'), (DECREE, '지방자치법 시행령(심의·공포·보고 절차 확인)'),
                (ADMIN, '행정절차법(입법예고·예외·기간 확인)'), (GUIDE, '법제처 2022 자치법규 입안 길라잡이(현행법 재대조)')]],
        'limits': '일반 안내입니다. 링크 본문을 이번 호출에서 읽은 것은 아닙니다. 현행 개별법·우리 법제사무 규정·실제 증빙이 우선합니다.'
    }


def screen_procedure(p: ProcedureInput, as_of: date, documents=()) -> dict:
    """Deterministic hold recommendations from declared dependencies and timelines."""
    findings = []
    def add(code, level, message, owner='담당자·법무부서', needed=None):
        findings.append({'code': code, 'severity': level, 'message': message,
            'owner': owner, 'required_evidence': needed or [], 'basis': 'INPUT_SCREENING_NOT_LEGAL_VERDICT'})
    formal = p.action in {'promulgate', 'implement', 'remediate'}
    d = p.dates
    if p.jurisdiction in {'서구', '북구', '남구', '동구', '중구', '강서구', '고성군'}:
        add('AMBIGUOUS_JURISDICTION', 'hold', '동명 지역이 있어 정식 지자체를 확인해야 합니다.')
    if p.basis_kind == 'unknown' or not p.basis_title or not p.basis_article:
        add('BASIS_UNRESOLVED', 'hold' if formal else 'pending', '근거 유형·제명·조문을 확인하세요. 개정안 또는 다른 지역 사례만으로 집행하지 않습니다.')
    if p.final_text_matches == 'no':
        add('FINAL_TEXT_MISMATCH', 'hold', '의회 최종 의결문/현행 근거와 규칙안이 다릅니다. 조문·별표·금액·서식을 다시 맞추세요.')
    elif p.final_text_matches == 'unknown':
        add('FINAL_TEXT_NOT_CHECKED', 'hold' if formal else 'pending', '현행 근거 또는 의결 최종문과 조문·별표·부칙 대응을 확인하지 않았습니다.')
    if p.basis_kind == 'ordinance_amendment':
        if p.ordinance_stage in {'rejected', 'withdrawn', 'reconsideration'}:
            add('DEPENDENCY_UNRESOLVED', 'hold', '부결·철회·재의 상태입니다. 종전 근거와 의존 내용을 재검토하세요.')
        elif p.ordinance_stage not in {'council_passed', 'promulgated', 'effective'}:
            add('NO_PLENARY_ADOPTION', 'hold' if formal or 'rule_promulgation' in d else 'pending',
                '개정 조례의 본회의 의결이 확인되지 않았습니다. 상임위 통과·예정일·결재 완료로 대신할 수 없습니다.', needed=['본회의 의결 최종문'])
        if formal or 'rule_promulgation' in d:
            for field, label in [('ordinance_vote', '본회의 의결일'), ('ordinance_promulgation', '조례 공포일'), ('basis_effective', '근거 조항 시행일')]:
                if field not in d:
                    add('MISSING_'+field.upper(), 'hold', label+' 및 원문 증빙이 없습니다. 선행 조건을 확인하세요.')
        if d.get('ordinance_vote') and d['ordinance_vote'] > as_of and formal:
            add('VOTE_STILL_PLANNED', 'hold', '본회의 의결일이 검토 기준일보다 미래입니다. 의결 완료로 보고하지 않습니다.')
        if d.get('ordinance_promulgation') and d['ordinance_promulgation'] > as_of and formal:
            add('BASIS_NOT_YET_PROMULGATED', 'hold', '근거 조례 공포일이 미래입니다. 공포 예정과 공포 완료를 구분하세요.')
        for prerequisite in ['ordinance_vote', 'ordinance_promulgation']:
            if d.get(prerequisite) and d.get('rule_promulgation') and d['rule_promulgation'] < d[prerequisite]:
                add('RULE_BEFORE_'+prerequisite.upper(), 'hold', '개정 조례의 '+('의결' if prerequisite == 'ordinance_vote' else '공포')+'보다 규칙 공포가 앞섭니다. 발령 보류·법무 검토를 권고합니다.')
    # Every document's own chronology, including independent rules, is screened.
    for first, second in [('ordinance_submission', 'ordinance_vote'), ('ordinance_vote', 'ordinance_transmission'),
        ('ordinance_vote', 'ordinance_promulgation'), ('ordinance_promulgation', 'basis_effective'),
        ('rule_promulgation', 'rule_effective'), ('notice_start', 'notice_end')]:
        if d.get(first) and d.get(second) and d[second] < d[first]:
            add('DATE_ORDER_'+second.upper(), 'hold', f'{second}가 {first}보다 빠릅니다. 입력 오류·적용례·예외 근거를 확인하세요.')
    if p.instrument == 'rule':
        for event in ['rule_effective', 'implementation']:
            if d.get(event) and d.get('basis_effective') and d[event] < d['basis_effective']:
                add('BEFORE_BASIS_EFFECTIVE_'+event.upper(), 'hold', '규칙 시행·업무 적용이 근거 조항 시행보다 빠릅니다. 해당 부칙·조문별 적용일을 맞추세요.')
        if p.action in {'implement', 'remediate'}:
            for field in ['basis_effective', 'rule_promulgation', 'rule_effective']:
                if field not in d:
                    add('MISSING_'+field.upper(), 'hold', field+'와 공포·부칙 증빙을 확인하세요.')
            for field in ['basis_effective', 'rule_promulgation', 'rule_effective']:
                if field in d and d[field] > as_of:
                    add('NOT_YET_'+field.upper(), 'hold', '아직 공포·시행 시점이 오지 않았습니다. 현재 업무에 적용하지 않도록 법무 확인하세요.')
        if d.get('implementation') and d.get('rule_effective') and d['implementation'] < d['rule_effective']:
            add('IMPLEMENTATION_BEFORE_RULE', 'hold', '실제 업무 적용이 규칙 시행보다 앞섭니다. 이미 처리한 건과 추가 적용을 분리해 점검하세요.')
    if p.instrument == 'ordinance' and formal and p.ordinance_stage not in {'council_passed', 'promulgated', 'effective'}:
        add('ORDINANCE_NO_ADOPTION', 'hold', '조례 공포·시행 전 본회의 의결·재의 등 확정 경로를 확인하세요.')
    if p.instrument == 'ordinance' and formal:
        needed = ['ordinance_vote'] + (['ordinance_promulgation', 'basis_effective'] if p.action in {'implement', 'remediate'} else [])
        for field in needed:
            if field not in d:
                add('MISSING_'+field.upper(), 'hold', field+'와 의결문·공보·부칙 증빙을 확인하세요.')
            elif d[field] > as_of:
                add('NOT_YET_'+field.upper(), 'hold', '아직 선행 의결·공포·시행 시점이 오지 않았습니다.')
    if d.get('notice_start') and d.get('notice_end') and (d['notice_end']-d['notice_start']).days < 20:
        add('SHORT_NOTICE_REVIEW', 'pending', '입법예고 날짜 간격이 20일 미만입니다. 적용 법규·기간 계산·단축/생략 사유를 확인하세요. 자동 위법 판정은 아닙니다.')
    for step, state in p.steps.items():
        prerequisite = step not in {'gazette', 'system_forms', 'transition', 'budget'} or p.action in {'implement', 'remediate'}
        if state == 'pending' and formal and prerequisite:
            add('PENDING_'+step.upper(), 'hold', step+'가 미완료입니다. 적용되는 선행절차이면 완료 전 후속 발령·집행을 보류하세요.')
        elif state == 'pending':
            add('PENDING_'+step.upper(), 'pending', step+'의 완료 시점을 후속 업무 일정에 반영하세요. 준비 중인 단계 자체를 완료로 표시하지 않습니다.')
        elif state == 'not_applicable':
            add('EXEMPTION_'+step.upper(), 'pending', step+'의 비대상·면제 근거 및 내부 판단 증빙을 확인하세요.')
    if p.exception_reason:
        add('EXCEPTION_UNVERIFIED', 'pending', '입력한 예외 사유가 기존 보류 항목을 해제하지 않습니다. 법무 확인과 적용 조문이 필요합니다.')
    if formal:
        for step in ['law_review', 'ordinance_rule_committee', 'prior_report', 'notice']:
            if p.steps.get(step, 'unknown') == 'unknown':
                add('UNCONFIRMED_'+step.upper(), 'pending', step+'의 대상 여부·진행 상태·증빙이 미확인입니다.')
    # Official body retrieval can confirm a candidate and metadata, not delegation meaning.
    matched = [doc for doc in documents if p.basis_document_id and doc.document_id == p.basis_document_id
        and doc.source_state in {'live', 'cache'}
        and ((p.basis_kind == 'law' and doc.kind == 'law') or
             (p.basis_kind in {'current_ordinance', 'ordinance_amendment'} and doc.kind == 'ordinance'))]
    basis_docs = [doc.summary() for doc in matched]
    if matched:
        from .normalize import region_match, compact
        for doc in matched:
            if compact(doc.title) != compact(p.basis_title) or (doc.kind != 'law' and not region_match(doc.jurisdiction, p.jurisdiction)):
                add('OFFICIAL_BASIS_IDENTITY_MISMATCH', 'hold', '실제 조회한 근거의 제명·지자체와 입력이 다릅니다.')
            if p.basis_article and not any(compact(p.basis_article) == compact(a.label) for a in doc.articles if not a.deleted):
                add('BASIS_ARTICLE_NOT_FOUND', 'hold', '실제 원문에 지정한 근거 조문이 없습니다. 조·항·호별 적합성은 별도 검토하세요.')
            if doc.effective_date:
                try:
                    effective = date.fromisoformat(doc.effective_date) if '-' in doc.effective_date else date(int(doc.effective_date[:4]), int(doc.effective_date[4:6]), int(doc.effective_date[6:8]))
                    if 'basis_effective' in d and d['basis_effective'] != effective:
                        add('BASIS_DATE_DIFFERS', 'pending', '원문 전체 시행일과 입력한 근거 조항 시행일이 다릅니다. 부칙·조문별 시행일을 대조하세요.')
                    if formal and effective > as_of:
                        add('OFFICIAL_BASIS_FUTURE', 'hold' if p.action in {'implement', 'remediate'} else 'pending', '조회한 원문의 시행일이 미래입니다. 공포 준비와 실제 적용을 구분하고 조문별 예외·부칙을 확인하세요.')
                except (ValueError, IndexError):
                    add('OFFICIAL_BASIS_DATE_INVALID', 'pending', '원문 시행일을 해석하지 못했습니다. 공보·부칙에서 확인하세요.')
    if not matched:
        add('OFFICIAL_BASIS_NOT_RETRIEVED', 'pending', '이 점검에서 선택한 공식 근거 원문을 조회하지 않았습니다. 입력 날짜·URL은 사용자 제공 주장입니다.', needed=['ordinance_search → ID 선택 → ordinance_get_document'])
    if p.action == 'remediate':
        add('INCIDENT_REVIEW', 'hold', '법무부서에 경위·공포본·의결문을 보고하고 요금·신청·지급·처분·시스템 등 적용 내역을 보존하세요. 추가 적용 보류 여부와 정정/개정/폐지·권리보호 조치를 검토하며 자동 소급치유·환급을 단정하지 않습니다.')
    holds = [f['code'] for f in findings if f['severity'] == 'hold']
    guide = procedure_guide()
    return {'status': 'HOLD_RECOMMENDED' if holds else 'EVIDENCE_REVIEW_REQUIRED',
        'legal_approval': False, 'publication_ready': False, 'implementation_ready': False,
        'assessment_level': 'INPUT_AND_RETRIEVED_METADATA_SCREENING', 'as_of': as_of.isoformat(),
        'input_provenance': 'USER_PROVIDED_NOT_VERIFIED', 'input': p.model_dump(mode='json'),
        'findings': findings, 'hold_codes': holds, 'retrieved_basis_documents': basis_docs,
        'parallel_preparation': '초안·협의·적용되는 입법예고 준비는 병행할 수 있습니다. 최종문·근거·시점 확인 전 공포·현장 적용 승인을 뜻하지 않습니다.',
        'source_links': guide['source_links'], 'needed_evidence': guide['needed_evidence'],
        'limits': '법적 효력·위법성·무효를 확정하지 않습니다. 의안·공보 진행상태를 실시간 자동 조회한 결과도 아닙니다. 기준일·입력·실제 원문 범위 안에서 점검합니다.'}
