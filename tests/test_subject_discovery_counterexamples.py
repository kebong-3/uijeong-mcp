"""Independent subject-candidate evidence trust and certainty counterexamples."""
import pytest
from evidence_discovery import discover_subjects

def event(text,source='OFFICIAL_FETCHED',index=3):
    return {'source_kind':source,'event_id':'e1','speech':{'text':text,'citation':{
        'source_kind':source,'docid':'D1','turn_index':index}}}

@pytest.mark.parametrize('source',['SYNTHETIC','USER_PROVIDED','UNKNOWN','LOCAL_ARCHIVE'])
def test_nonofficial_outer_event_cannot_seed_subject(source):
    item=event('청년을 대상으로 문화공간을 운영합니다.',source)
    item['speech']['citation']['source_kind']='OFFICIAL_FETCHED'
    assert discover_subjects([item],'문화공간')==[]

@pytest.mark.parametrize('missing',['docid','turn_index'])
def test_unlocated_quote_cannot_seed_subject(missing):
    item=event('청년을 대상으로 문화공간을 운영합니다.')
    del item['speech']['citation'][missing]
    assert discover_subjects([item],'문화공간')==[]

def test_unrelated_target_is_candidate_only_and_keeps_actual_quote():
    text='고령자를 대상으로 복지관을 운영합니다. 청년을 대상으로 문화공간을 운영합니다.'
    rows=discover_subjects([event(text)],'문화공간')
    assert rows[0]['term']=='청년'
    for row in rows:
        assert row['same_project_verified'] is False
        assert row['applicability_verified'] is False
        assert row['amount_attribution_verified'] is False
        loc=row['locator']
        assert text[loc['char_start']:loc['char_end']].strip()==row['quote']
        assert not any(key in row for key in ['amount','confirmed_budget','upper_project'])

@pytest.mark.parametrize('index',[-1,'3',True])
def test_invalid_locator_cannot_seed_subject(index):
    assert discover_subjects([event('청년을 대상으로 문화공간을 운영합니다.',index=index)],'문화공간')==[]
