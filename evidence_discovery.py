"""Bounded title-shaped lookup hints from located official meeting quotes.

Does not certify project identity, funding attribution or applicability.
"""
import copy
import re

_OFFICIAL = {'CLIK', 'COUNCIL_SITE', 'OFFICIAL_SITE', 'PUBLIC_API', 'OFFICIAL_FETCHED', 'OFFICIAL'}
_UNVERIFIED = {'SYNTHETIC', 'USER', 'USER_PROVIDED', 'LOCAL_ARCHIVE', 'UNKNOWN'}
_TITLE = re.compile(r'[가-힣A-Za-z0-9·]+(?:\s+[가-힣A-Za-z0-9·]+){0,7}?\s*(?:조례|지원사업|운영사업|조성사업|활성화(?!\s*(?:지원사업|운영사업|조성사업))|지원(?!사업|\s*조례|대상|금액))')
_CLAUSE = re.compile(r'[^\n,.。;:!?]+')
_SENTENCE = re.compile(r'[^\n.。!?]+')
_PREFIX = re.compile(r'^(?:(?:다음은|그리고|또한|아울러|관련|우리|저희|현재|올해|작년|내년|해당|본|먼저|다음|대해서는|사업은|사업으로|예산은|예산으로|추진하는|추진하고|대한|관한|위한)\s+|\d{4}년(?:도)?\s*)+')


def _turns(event):
    for key in ('question', 'speech'):
        if isinstance(event.get(key), dict):
            yield event[key]
    if isinstance(event.get('answers'), list):
        yield from (v for v in event['answers'] if isinstance(v, dict))


def discover_candidates(items: list[dict], topic: str = '', limit: int = 3) -> dict:
    """At most three candidates per domain; every candidate keeps its source.

    This is title-shape extraction, not semantic or same-project verification.
    """
    if not isinstance(items, list) or type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError('items는 근거 목록이며 limit은 1~3입니다.')
    result = {'ordinance': [], 'budget': [], 'same_project_verified': False,
              'method': 'OFFICIAL_QUOTE_TITLE_SHAPE_CANDIDATES',
              'limitations': ['원문 언급에서 얻은 검색 후보입니다. 동일사업·상하위사업 관계·금액 귀속·조례 적용은 미확인입니다.']}
    seen = {'ordinance': {}, 'budget': {}}
    for event in items[:200]:
        if not isinstance(event, dict):
            continue
        event_kind = str(event.get('source_kind', '')).upper()
        for turn in _turns(event):
            citation = turn.get('citation')
            if not isinstance(citation, dict):
                continue
            source_kind = str(citation.get('source_kind', '')).upper()
            if event_kind in _UNVERIFIED or source_kind in _UNVERIFIED:
                continue
            if (event_kind or source_kind) not in _OFFICIAL:
                continue
            if not (citation.get('record_id') or citation.get('docid')) or citation.get('turn_index') is None:
                continue
            text = turn.get('text')
            if not isinstance(text, str) or not text.strip() or len(text) > 100000:
                continue
            for clause in _CLAUSE.finditer(text):
                context = clause.group().strip()
                sentence = next((s for s in _SENTENCE.finditer(text) if s.start() <= clause.start() < s.end()), clause)
                quote = sentence.group().strip()
                for match in _TITLE.finditer(context):
                    name = re.sub(r'^(?:우리|저희)\s+(?:시|군|구)\s+', '', match.group().strip())
                    name = re.sub(r'^(?:에\s*따라|에\s*따른|를|을|와|과|및)\s+', '', name)
                    name = _PREFIX.sub('', name)
                    name = re.split(r'\s+\S+(?:했고|하며|이며|이고|있고|있으며|으로)\s+', name)[-1].strip()
                    name = re.split(r'\s(?:대해|하는|하고|있고|있으며|으로|에는|대해서는|위해|위한)\s+', name)[-1].strip()
                    if not 4 <= len(name) <= 80 or name in {'사업 지원', '운영 지원', '예산 지원', '관련 조례', '지원사업', '운영사업', '조성사업', '활성화'}:
                        continue
                    domain = 'ordinance' if name.endswith('조례') else 'budget'
                    key = re.sub(r'\s+', '', name).casefold()
                    evidence = {'quote': quote, 'citation': copy.deepcopy(citation),
                                'locator': {'turn_index': citation['turn_index'], 'char_start': sentence.start(),
                                            'char_end': sentence.end(), 'offset_basis': 'TURN_TEXT'},
                                'source_event_id': event.get('event_id')}
                    if key in seen[domain]:
                        existing = seen[domain][key]
                        if evidence not in existing['evidence'] and len(existing['evidence']) < 3:
                            existing['evidence'].append(evidence)
                        continue
                    if len(result[domain]) >= 60:
                        continue
                    candidate = {'term': name, 'kind': 'OFFICIAL_MENTION_CANDIDATE',
                                 **copy.deepcopy(evidence), 'same_project_verified': False,
                                 'applicability_verified': False, 'amount_attribution_verified': False,
                                 'evidence': [evidence],
                                 'discovery_rank': [0 if topic and topic in quote else 1,
                                                    abs(sentence.start() - text.find(topic)) if topic and topic in text else 1000000]} 
                    result[domain].append(candidate)
                    seen[domain][key] = candidate
    for domain in ('ordinance', 'budget'):
        result[domain].sort(key=lambda candidate: candidate['discovery_rank'])
        result[domain] = result[domain][:limit]
    result['ranking'] = 'EXACT_TOPIC_SENTENCE_THEN_SAME_TURN_DISTANCE_THEN_SOURCE_ORDER'
    return result
