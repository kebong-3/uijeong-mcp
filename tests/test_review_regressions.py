import pytest
from jachi.normalize import parse_document, region_match
from jurisdiction_identity import resolve_jurisdiction
from query_decomposition import decompose, legal_search_plan
from integrated_workflow import local_workflow_plan


def payload(rows):
    return {'자치법규': {'자치법규명':'가상시 시설 지원 조례', '자치법규ID':'123',
                        '자치법규일련번호':'456', '조':rows,
                        '부칙':{'부칙내용':'이 조례는 공포일부터 시행한다.'},
                        '별표':{'별표제목':'별표 1', '별표내용':'시설 목록'}}}

@pytest.mark.parametrize('raw,text,label',[
    ('5','제5조(운영) 시설을 운영한다.','제5조'),
    ('502000502','제5조의2(지원) ① 시설 1. 운영 가. 지원','제5조의2'),
    ('opaque-id','제10조의3(절차) 지원한다.','제10조의3'),
    ('6','제6조 삭제','제6조'),
])
def test_source_headings_are_identifiers_not_opaque_api_numbers(raw,text,label):
    doc=parse_document(payload([{'조문번호':raw,'조내용':text}]),'ordinance')
    article=doc.articles[0]
    assert article.label==label and article.key=='main:'+label
    assert article.raw_number==raw and article.text==text
    assert article.source_heading==label
    assert doc.supplementary and doc.annexes
    if label=='제6조': assert article.deleted


def test_recognizable_number_heading_conflict_blocks_downstream_document():
    with pytest.raises(ValueError,match='불일치'):
        parse_document(payload([{'조문번호':'5','조내용':'제6조 다른 조문'}]),'ordinance')

@pytest.mark.parametrize('alias',['수원','수원시','수원특례시','경기도 수원시','수원시의회'])
def test_region_alias_matches_unique_registry_identity(alias):
    assert region_match('경기도 수원시',alias)
    assert resolve_jurisdiction(alias)['council_id']=='031014'

@pytest.mark.parametrize('alias',['중구','서구','광주시','광주'])
def test_ambiguous_region_never_silently_matches(alias):
    assert resolve_jurisdiction(alias)['state']=='ambiguous'
    assert not region_match('경기도 광주시',alias)


def test_independent_region_examples_and_institution_types():
    assert region_match('부산광역시 부산진구','부산진구')
    assert not region_match('부산광역시 중구','서울특별시 중구')
    assert resolve_jurisdiction('수원시의회')['institution_type']=='council'
    assert resolve_jurisdiction('수원시')['institution_type']=='local_government'

@pytest.mark.parametrize('question',[
 '수원 빌라가꿈관리사무소 관련 조례, 2026년 본예산·추경·예산현액·집행액과 2025년부터 2026년 10월 4일까지 의회 지적사항을 찾아줘.',
 '2026년 본예산·추경·집행액과 의회 지적사항을 수원 빌라가꿈관리사무소 관련 조례로 검토해줘.',
])
def test_budget_attributes_do_not_replace_project(question):
    plan=local_workflow_plan(question,'수원시',2026,'2026-10-04',['council','budget','ordinance'])
    budget=next(s for s in plan['steps'] if s['domain']=='budget')
    assert budget['arguments_template']['topic']=='빌라가꿈관리사무소'
    assert plan['decomposition']['budget_stages'][:2]==['original','supplementary']
    assert not legal_search_plan(question,'수원시')['law_queries']
    assert all('<' not in str(c) for s in plan['steps'] for c in s['executable_calls'])


def test_other_project_phrase_and_budget_named_policy_preserved():
    result=decompose('부산진구 청년 월세 지원 관련 2025년 본예산·추경과 2026년 집행액을 찾아줘.','부산진구')
    assert result['target_entities'][0]['name']=='청년 월세 지원'
    assert '본예산' not in result['search_terms']
    policy=local_workflow_plan('서구 주민참여예산 사업 본예산 검토해줘','서구',2026,'2026-10-04',['budget'])
    assert policy['status']=='NEEDS_CONTEXT'
    assert policy['steps'][0]['arguments_template']['topic']=='주민참여예산'
    assert not policy['steps'][0]['executable_calls']


def test_department_target_is_not_particle_stripped():
    result=decompose('문화예술과 2024년부터 2026년 예산과 의회 지적사항을 찾아줘','부산진구')
    assert result['target_entities'][0]['name']=='문화예술과'
    assert result['target_entities'][0]['type']=='department'


def test_explicit_meeting_period_and_remaining_budget_stage_are_inspectable():
    q='2025년부터 2026년 10월 4일까지 수원 빌라가꿈관리소의 의회 지적사항과 2026년 본예산·추경·집행액을 확인해줘'
    plan=local_workflow_plan(q,'수원시',2026,'2026-10-04',['council','budget'])
    council=plan['steps'][0]['executable_calls'][0]['arguments']
    assert council['date_from']=='2025-01-01' and council['date_to']=='2026-10-04'
    budget=plan['steps'][1]
    assert budget['arguments_template']['topic']=='빌라가꿈관리소'
    assert budget['scope']['remaining_stage_evidence_required']==['supplementary','execution']
    assert '확인해줘' not in plan['decomposition']['search_terms']


def test_unidentifiable_article_is_not_silently_dropped_from_partial_document():
    with pytest.raises(ValueError,match='조문 식별 실패'):
        parse_document(payload([{'조문번호':'1','조내용':'제1조 지원'},
                                {'조문번호':'opaque','조내용':'번호 없는 다른 내용'}]),'ordinance')


def test_legacy_legal_reader_uses_shared_article_identity_and_blocks_conflict():
    from legal_context import _article_rows
    raw=payload([{'조문번호':'502000502','조내용':'제5조의2(지원) 시설 지원'}])
    legacy=_article_rows(raw,'시설')[0]
    parsed=parse_document(raw,'ordinance').articles[0]
    assert legacy['article']==parsed.label=='제5조의2'
    assert legacy['source_heading']==parsed.source_heading
    assert legacy['raw_number']==parsed.raw_number
    with pytest.raises(ValueError,match='불일치'):
        _article_rows(payload([{'조문번호':'5','조내용':'제6조 시설 지원'}]),'시설')


def test_legacy_law_reader_keeps_law_number_contract():
    from legal_context import _article_rows
    assert _article_rows({'조문번호':'001002','조문내용':'시설 지원'},'시설',kind='law')[0]['article']=='제10조의2'
