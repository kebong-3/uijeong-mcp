"""Independent counterexamples for regional attribution and finance certainty."""
import pytest
import openai_compat as O
from budget_evidence import fiscal_basis
from evidence_core import merge_events

@pytest.mark.parametrize('query',['중구의회 보육','서구의회 청년지원','광주시의회 공동주택','광주 공동주택'])
def test_ambiguous_search_cannot_silently_choose_region(query):
    with pytest.raises(ValueError, match='모호'):
        O._best_council(query)

@pytest.mark.parametrize('query,expected',[
 ('부산광역시 중구의회 보육','부산광역시 중구의회'),
 ('경기도 광주시의회 공동주택','경기도 광주시의회'),
 ('수원시의회 공동주택','경기도 수원시의회')])
def test_explicit_search_jurisdiction(query,expected):
    assert O._best_council(query)[0]==expected

def test_empty_current_does_not_certify_budget():
    basis=fiscal_basis('current','20261003',False)
    assert basis['requested_stage_supported'] is True
    assert basis['requested_stage_verified'] is False
    assert basis['amount_verified'] is False
    assert basis['same_project_verified'] is False

@pytest.mark.parametrize('stage',['original','supplementary','draft','settlement'])
def test_related_current_row_never_becomes_requested_stage(stage):
    basis=fiscal_basis(stage,'20261003',True)
    assert basis['returned_stage']=='current'
    assert basis['requested_stage_verified'] is False
    assert basis['amount_unit']=='SOURCE_CONFIRMATION_REQUIRED'

def test_event_merge_keeps_query_provenance_and_does_not_mutate_inputs():
    events=[{'event_id':'e','matched_query':'도서관','speech':{'text':'발언'}},
            {'event_id':'e','matched_query':'도서 관','speech':{'text':'발언'}}]
    output=merge_events(events)
    assert len(output)==1
    assert output[0]['matched_queries']==['도서관','도서 관']
    assert 'matched_queries' not in events[0]

def test_revised_source_body_remains_a_distinct_event():
    from evidence_core import parse_turns, make_record, record_events
    meta={'DOCID':'d','RASMBLY_NM':'가상시의회','MTG_DE':'20260101'}
    first=make_record(meta,parse_turns('○기획과장 이가상: 도서관 지원사업을 보고합니다.'),source='CLIK')
    revised=make_record(meta,parse_turns('○기획과장 이가상: 도서관 지원사업을 수정 보고합니다.'),source='CLIK')
    events=record_events(first,'도서관',mode='발언')+record_events(revised,'도서관',mode='발언')
    assert len(events)==2
    assert len(merge_events(events))==2
