from integrated_workflow import EvidenceItem, local_evidence_review, local_workflow_plan


def test_composite_plan_does_not_claim_retrieval_or_guess_region():
    plan = local_workflow_plan('의회 추경 질의와 조례 개정 검토')
    assert plan['domains'] == ['council', 'budget', 'ordinance']
    assert plan['evidence_retrieved'] is False
    assert plan['status'] == 'NEEDS_CONTEXT'
    assert plan['steps'][0]['arguments_template']['council'] == '<확인 필요>'


def test_single_domain_avoids_fanout():
    plan = local_workflow_plan('경로당 예산 조회', '광주 서구', 2026)
    assert plan['domains'] == ['budget']
    assert len(plan['steps']) == 1


def test_explicit_domains_support_topic_without_keywords():
    assert local_workflow_plan('경로당', '광주 서구', domains=['council'])['domains'] == ['council']
    assert local_workflow_plan('검색', domains=['unknown'])['status'] == 'INVALID_INPUT'
    assert local_workflow_plan('조례', as_of='2026-99-20')['status'] == 'INVALID_INPUT'


def test_error_and_user_input_are_not_evidence():
    review = local_evidence_review([
        EvidenceItem(domain='council', state='error'),
        EvidenceItem(domain='budget', state='user_provided', source_ref='user.txt')
    ], required_domains=['council', 'budget'])
    assert review['verified_facts'] is False
    assert review['missing_evidence_domains'] == ['council', 'budget']


def test_mismatch_partial_and_version_are_visible():
    review = local_evidence_review([
        EvidenceItem(domain='budget', state='partial', source_ref='official:1', jurisdiction='부산 서구', fiscal_year=2025),
        EvidenceItem(domain='ordinance', state='retrieved', source_ref='law:1')
    ], jurisdiction='광주 서구', fiscal_year=2026)
    assert len(review['issues'][0]['issues']) == 4
    assert any('기준일' in x for x in review['issues'][1]['issues'])


def test_ambiguous_jurisdiction_requires_context():
    plan = local_workflow_plan('의회 예산 질의', '서구', 2026)
    assert plan['status'] == 'NEEDS_CONTEXT'
    assert '대상 지자체(동명 지역 구분)' in plan['missing_context']


def test_complete_composite_plan_and_interface_templates():
    plan = local_workflow_plan('의회 예산 조례 검토', '광주 서구', 2026, '2026-09-30')
    assert plan['status'] == 'PLAN_ONLY'
    assert plan['missing_context'] == []
    assert [s['tool'] for s in plan['steps']] == ['council_evidence_bundle', 'council_finance_context', 'ordinance_search']
    assert 'reference' in plan['steps'][2]['next']
