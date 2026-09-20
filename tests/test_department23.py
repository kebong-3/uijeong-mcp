"""부서 기준 진입·반복 쟁점·기관 서식(v2.3) 검사.

세 도구가 지키는 선: 부서 분류는 발언자 표기 기준이고, 반복은 질의 성격 발언만 세며,
서식은 판단이 필요한 칸을 비운 채 담당자 확인 대상으로 남긴다.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dept_core as D
import evidence_core as E
import uijeong_mcp as U

QA = ('<b>○김가상 위원</b> 노인복지관 급식 위생점검은 어떻게 합니까?<br>'
      '<b>○노인복지과장 이가상</b> 분기마다 점검하며 결과는 10월 5일까지 제출하겠습니다.<br>')
PROXY = ('<b>○박가상 위원</b> 미래전략과 소관 청사 이전 계획을 밝혀 주십시오.<br>'
         '<b>○미래전략팀장 최가상</b> 과장을 대신해 답변드립니다. 내년에 검토하겠습니다.<br>')
OTHER = ('<b>○김가상 위원</b> 노인복지과 예산은 총무과가 배정합니까?<br>'
         '<b>○총무과장 정가상</b> 저희가 배정합니다.<br>')


def events(body, doc='D1', date='20250101'):
    record = E.make_record({'DOCID': doc, 'RASMBLY_ID': '062006', 'MTG_DE': date},
                           E.parse_turns(body), source='CLIK')
    return E.record_events(record, '', '질의답변'), E.record_events(record, '', '약속')


# ── 부서 어간과 일치 ────────────────────────────────────────────────────────
@pytest.mark.parametrize('name,stem', [('기획실', '기획'), ('미래전략과장', '미래전략'),
                                       ('노인복지과', '노인복지'), ('감사담당관', '감사'),
                                       ('과', '과')])
def test_department_stem(name, stem):
    assert D.department_stem(name) == stem


def test_proxy_answer_by_team_leader_counts_as_department():
    assert D.matches_department('미래전략팀장 최가상', '미래전략과')
    assert not D.matches_department('총무과장 정가상', '노인복지과')
    assert not D.matches_department('노인복지과장 이가상', '')


def test_classification_splits_answered_unanswered_other():
    qa, _ = events(QA)
    mention, _ = events(OTHER, doc='D2')
    groups = D.classify_department_events(qa + mention, '노인복지과')
    assert len(groups['answered']) == 1
    assert groups['answered'][0]['matched_by'].startswith('답변자 직함')
    assert len(groups['other_mention']) == 1
    assert groups['answered'][0]['answers'][0]['speaker'] == '노인복지과장 이가상'


def test_unanswered_is_scope_statement_not_verdict():
    body = '<b>○김가상 위원</b> 노인복지과 급식 점검 계획을 제출해 주십시오.<br>'
    qa, _ = events(body)
    groups = D.classify_department_events(qa, '노인복지과')
    assert not groups['answered'] and len(groups['unanswered']) == 1
    row = groups['unanswered'][0]
    assert row['answer_link_status'] == 'NOT_LINKED_IN_SCOPE'
    assert '확인 범위' in row['matched_by'], '답변하지 않았다는 판정으로 읽히면 안 된다'


def test_commitments_never_judge_fulfillment_and_dedupe():
    _, promises = events(QA)
    _, copies = events(QA, doc='D2')
    rows = D.department_commitments(promises + copies, '노인복지과')
    assert rows, '자료제출 확약이 후보로 잡혀야 한다'
    assert all(r['fulfillment_status'] == 'EVIDENCE_NOT_VERIFIED' for r in rows)
    marks = {(r['commitment_type'], r['excerpt'], r['deadline_verbatim']) for r in rows}
    assert len(marks) == len(rows), '같은 문면은 한 번만 남아야 한다'


def test_commitment_of_other_department_is_excluded():
    _, promises = events(PROXY)
    assert D.department_commitments(promises, '노인복지과') == []


# ── 반복 집계 ──────────────────────────────────────────────────────────────
def test_recurring_counts_questions_only_and_needs_two_years():
    rows = []
    for year in ('20230101', '20240101'):
        qa, _ = events(QA, doc='D' + year, date=year)
        rows.extend(qa)
    table = D.recurring_terms(rows, U.extract_terms, min_years=2, top=10)
    terms = {item['term'] for item in table['items']}
    assert '위생점검' in terms or '노인복지관' in terms
    assert '분기' not in terms, '답변에 나온 말을 의회의 요구로 세면 안 된다'
    assert table['observed_years'] == ['2023', '2024']
    assert any('예측' in line for line in table['limitations'])


def test_recurring_single_year_yields_nothing():
    qa, _ = events(QA)
    assert D.recurring_terms(qa, U.extract_terms, min_years=2)['items'] == []


@pytest.mark.parametrize('kwargs', [{'min_years': 0}, {'top': 0}, {'top': 999}, {'min_years': True}])
def test_recurring_rejects_bad_limits(kwargs):
    with pytest.raises(ValueError):
        D.recurring_terms([], U.extract_terms, **kwargs)


# ── 서식 ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('label,shown', [('개요', '개    요'), ('현 실태', '현 실태'),
                                         ('검토결과', '검토결과'), ('행정사항', '행정사항')])
def test_pad_label_only_widens_two_character_labels(label, shown):
    assert D.pad_label(label) == shown


@pytest.mark.parametrize('raw,shown', [('20261225', '2026.12.25.'), ('2026-12-25', '2026.12.25.'),
                                       ('', ''), ('미상', '미상')])
def test_meeting_date_is_written_as_official_documents_do(raw, shown):
    assert D.format_meeting_date(raw) == shown


def worksheet(form='5분자유발언_회의자료', **kw):
    qa, promises = events(QA)
    groups = D.classify_department_events(qa, '노인복지과')
    params = dict(topic='노인복지관 급식', department='노인복지과', council='광주 서구',
                  evidence=groups['answered'], facts=[], commitments=[], prepared_on='2026-09-20')
    params.update(kw)
    return D.build_worksheet(form, **params)


@pytest.mark.parametrize('form', sorted(D.FORMS))
def test_every_form_leaves_judgement_cells_blank(form):
    sheet = worksheet(form)
    blanks = [s for s in sheet['sections'] if s['entries'] is None]
    assert blanks, '판단이 필요한 칸은 비워 둬야 한다'
    assert all(s['status'] == D.CONFIRM for s in blanks)
    assert D.CONFIRM in sheet['plain_text']


def test_worksheet_places_evidence_and_facts_in_their_own_cells():
    sheet = worksheet(facts=[{'id': 'F1', 'text': '급식 인원은 120명이다.',
                              'document_ref': '운영일지 3쪽', 'as_of': '2026-09-19'}])
    filled = {s['content_source'] for s in sheet['sections'] if s['entries']}
    assert '확인된 회의록 근거' in filled and '담당자 제공자료(USER_PROVIDED)' in filled
    assert '2025.01.01.' in sheet['plain_text']
    assert '운영일지 3쪽' in sheet['plain_text']


def test_worksheet_rejects_unknown_form_and_bad_date():
    with pytest.raises(ValueError):
        worksheet('알수없는서식')
    with pytest.raises(ValueError):
        worksheet(prepared_on='2026-13-40')


# ── 도구 수준 ──────────────────────────────────────────────────────────────
def meta(doc='D1', body=QA, name='복지건설위원회', date='20250101'):
    return dict(DOCID=doc, MINTS_HTML=body, RASMBLY_ID='062006', RASMBLY_NM='가상서구의회',
                RASMBLY_NUMPR='9', RASMBLY_SESN='300', MINTS_ODR='1', MTGNM=name, MTG_DE=date)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    U.clik._cache.clear()
    monkeypatch.setattr(U, 'API_KEY', 'TEST-ONLY')
    from runtime_security import SQLiteBudget
    monkeypatch.setattr(U.clik, '_budget', SQLiteBudget(tmp_path / 'budget.db', 1000))
    data = {'rows': [meta()], 'calls': []}

    async def raw(path, params):
        data['calls'].append(params.copy())
        if params.get('displayType') == 'detail':
            return [{'RESULT_CODE': 'SUCCESS',
                     **next(r for r in data['rows'] if r['DOCID'] == params['docid'])}]
        start = params.get('startCount', 0)
        return [{'RESULT_CODE': 'SUCCESS', 'TOTAL_COUNT': len(data['rows']),
                 'LIST': [{'ROW': r} for r in data['rows'][start:start + 100]]}]

    monkeypatch.setattr(U.clik, '_raw_get', raw)
    return data


def run(coro):
    return asyncio.run(coro)


def test_brief_finds_events_whose_department_is_only_in_the_speaker_label(fake):
    result = run(U.council_department_brief('노인복지과', source='clik', max_docs=2))
    assert result['status'] != 'EMPTY'
    assert result['totals']['answered'] >= 1
    assert result['answered_items'][0]['answers'][0]['speaker'] == '노인복지과장 이가상'
    assert result['search_terms'][0] == '노인복지과'
    assert result['stored'] is False
    assert result['next_step']['tool'] == 'council_recurring_issues'


def test_brief_reports_empty_without_inventing_matches(fake):
    result = run(U.council_department_brief('환경위생과', source='clik', max_docs=2))
    assert result['status'] == 'EMPTY'
    assert result['totals']['department_matched'] == 0
    assert result['answered_items'] == []


@pytest.mark.parametrize('kwargs', [{'department': ''}, {'department': '기획실', 'limit': 0},
                                    {'department': '기획실', 'max_docs': 99},
                                    {'department': '기획실', 'source': '엉뚱'}])
def test_brief_rejects_bad_input(fake, kwargs):
    assert run(U.council_department_brief(**kwargs))['status'] == 'INVALID_INPUT'


def test_brief_snapshot_is_reusable_by_worksheet(fake):
    brief = run(U.council_department_brief('노인복지과', source='clik', max_docs=2))
    ident = brief['answered_items'][0]['event_id']
    sheet = run(U.council_format_worksheet(form='구정질문_답변서', topic='노인복지관 급식',
                                           department='노인복지과', snapshot_id=brief['snapshot_id'],
                                           event_ids=[ident], prepared_on='2026-09-20'))
    assert sheet['status'] != 'INVALID_INPUT'
    assert '위생점검' in sheet['plain_text']


def test_worksheet_rejects_event_id_from_another_bundle(fake):
    brief = run(U.council_department_brief('노인복지과', source='clik', max_docs=2))
    bad = run(U.council_format_worksheet(form='구정질문_답변서', topic='주제', department='노인복지과',
                                         snapshot_id=brief['snapshot_id'], event_ids=['evt_없음']))
    assert bad['status'] == 'INVALID_INPUT'


def test_recurring_issues_counts_years_not_members(fake):
    fake['rows'] = [meta('D23', date='20230301'), meta('D24', date='20240301'),
                    meta('D25', date='20250301')]
    result = run(U.council_recurring_issues(department='노인복지과', years=3,
                                            include_current_year=False, as_of='2026-09-20',
                                            max_docs_per_year=2))
    assert result['anchor_kind'] == 'department'
    assert [row['meeting_year'] for row in result['per_year']] == [2023, 2024, 2025]
    assert result['events_examined'] >= 3
    assert result['recurring'] and result['recurring'][0]['year_count'] >= 2
    assert all('의원' not in str(item) for item in result['recurring'])
    assert any('예측' in line for line in result['limitations'])


def test_recurring_issues_requires_an_anchor(fake):
    assert run(U.council_recurring_issues())['status'] == 'INVALID_INPUT'
    assert run(U.council_recurring_issues(keyword='급식', years=1))['status'] == 'INVALID_INPUT'


def test_new_tools_are_in_work_and_lite_profiles():
    assert U.DEPARTMENT_TOOLS <= U.WORK_TOOLS <= U.LITE_TOOLS
    assert 'council_department_brief' in U.WORK_TOOLS
