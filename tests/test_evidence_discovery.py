from evidence_discovery import discover_candidates


def event(text, source='CLIK', index=7):
    return {'event_id': 'e1', 'source_kind': source, 'speech': {'text': text,
            'citation': {'record_id': 'r1', 'docid': 'd1', 'turn_index': index, 'source_kind': source}}}


def test_multiple_projects_preserve_context_without_amount_attribution():
    text = '공동주택 관리 운영사업 2억 2,000만원, 녹색건축물 조성 지원사업 7억 8,000만원, 소규모 공동주택 활성화 4억원입니다.'
    result = discover_candidates([event(text)])
    assert [v['term'] for v in result['budget']] == ['공동주택 관리 운영사업', '녹색건축물 조성 지원사업', '소규모 공동주택 활성화']
    assert all(v['same_project_verified'] is False and v['amount_attribution_verified'] is False for v in result['budget'])
    assert all('amount' not in v for v in result['budget'])
    assert all(v['quote'] == text[:-1] for v in result['budget'])
    for candidate in result['budget']:
        locator = candidate['locator']
        assert text[locator['char_start']:locator['char_end']].strip() == candidate['quote']


def test_other_region_title_and_duplicate_evidence():
    first = event('부산광역시 부산진구 청년 주거 지원 조례를 검토합니다.')
    second = event(first['speech']['text'], index=8)
    result = discover_candidates([first, second])
    assert result['ordinance'][0]['term'] == '부산광역시 부산진구 청년 주거 지원 조례'
    assert len(result['ordinance']) == 1
    assert len(result['ordinance'][0]['evidence']) == 2
    assert result['ordinance'][0]['applicability_verified'] is False


def test_unverified_or_unlocated_cannot_seed_candidates():
    missing = event('문화예술 활성화 지원사업')
    del missing['speech']['citation']['turn_index']
    forged = event('문화예술 활성화 지원사업', source='USER_PROVIDED')
    forged['speech']['citation']['source_kind'] = 'OFFICIAL'
    result = discover_candidates([missing, forged, event('문화예술 활성화 지원사업', source='SYNTHETIC')])
    assert not result['budget'] and not result['ordinance']


def test_limit_and_qa():
    result = discover_candidates([event(f'정책{i} 운영사업') for i in range(6)], limit=2)
    assert len(result['budget']) == 2
    qa = event('해당 문화예술 지원사업은 어떻게 됩니까?')
    qa['question'] = qa.pop('speech')
    assert discover_candidates([qa])['budget'][0]['term'] == '문화예술 지원사업'


def test_amount_narration_does_not_become_title():
    text = '건축과는 사업비 2억 2,000만원이라고 보고했고 소규모 공동주택 활성화 지원사업을 언급했습니다.'
    result = discover_candidates([event(text)])
    assert result['budget'][0]['term'] == '소규모 공동주택 활성화 지원사업'
    assert result['budget'][0]['quote'] == text[:-1]
    result = discover_candidates([event('우리 시 공동주택관리 지원 조례에 따른 사업입니다.')])
    assert result['ordinance'][0]['term'] == '공동주택관리 지원 조례'


def test_legal_title_conjunctions_preserved():
    for name in ('문화예술 진흥 및 지원 조례', '청년 주거 안정에 관한 조례'):
        assert discover_candidates([event(name+'를 검토합니다.')])['ordinance'][0]['term'] == name

def test_topic_ranking_does_not_certify_project_identity():
    text = '건축 기본계획 지원사업입니다. 녹색 건축 운영사업입니다. 도로 정비 지원사업입니다. 문화센터 운영사업입니다. 청년 주거 정책으로 청년 월세 지원사업입니다.'
    result = discover_candidates([event(text)], topic='청년 주거', limit=1)
    assert result['budget'][0]['term'] == '청년 월세 지원사업'
    assert result['budget'][0]['same_project_verified'] is False


def test_ordinance_and_project_in_one_sentence():
    text = '문화예술 진흥 및 지원 조례에 따라 문화예술 진흥 지원사업을 운영합니다.'
    result = discover_candidates([event(text)])
    assert result['ordinance'][0]['term'] == '문화예술 진흥 및 지원 조례'
    assert result['budget'][0]['term'] == '문화예술 진흥 지원사업'
    assert result['budget'][0]['quote'] == text[:-1]


def test_report_narration_prefix_is_not_a_search_title():
    result = discover_candidates([event('보고드리면 법적 근거 마련을 위해 수원시 건축 기본 조례를 제정했습니다.')])
    assert result['ordinance'][0]['term'] == '수원시 건축 기본 조례'
    result = discover_candidates([event('다음은 주민공동체 개선을 위한 소규모 공동주택 지원사업입니다.')])
    assert result['budget'][0]['term'] == '소규모 공동주택 지원사업'
