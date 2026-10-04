"""Conservative regional identity from the shipped, dated CLIK registry.

Council codes are discovery identifiers, not finance/law agency codes. Historic
aliases are recorded separately and are never treated as evidence of a merger.
"""
from __future__ import annotations
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def _compact(value: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or ''))


@lru_cache(maxsize=1)
def _registry() -> dict:
    return json.loads((Path(__file__).parent / 'data/council_codes.json').read_text())


def resolve_jurisdiction(value: str) -> dict:
    original = (value or '').strip()
    institution = 'council' if original.endswith('의회') else 'local_government'
    query = _compact(original).removesuffix('의회').replace('특례시', '시')
    data = _registry()
    matches = []
    for row in data['councils']:
        canonical = row['name'].removesuffix('의회')
        names = [canonical, *[n.removesuffix('의회') for n in row.get('aliases', [])]]
        variants = {_compact(n).replace('특례시', '시') for n in names}
        # Exact component aliases only. Never substring-match a region.
        for name in names:
            leaf = name.split()[-1]
            variants.add(_compact(leaf))
            if leaf.endswith(('시', '군', '구')) and len(leaf) > 2:
                variants.add(_compact(leaf[:-1]))
        if query and query in variants:
            matches.append({'council_id': row['council_id'], 'name': canonical,
                            'registry_status': row['status'],
                            'match_basis': 'EXACT_REGISTRY_NAME_OR_ALIAS' if query in {_compact(n).replace('특례시','시') for n in names} else 'REGISTRY_LOCALITY_COMPONENT'})
    # '광주시' is used ambiguously in ordinary questions; require a province.
    if query in {'광주', '광주시'}:
        matches = [dict(council_id=r['council_id'], name=r['name'].removesuffix('의회'),
                        registry_status=r['status']) for r in data['councils']
                   if r['council_id'] == '031006' or r['name'] == '광주광역시의회']
    unique = {m['council_id']: m for m in matches}
    candidates = list(unique.values())
    resolved = candidates[0] if len(candidates) == 1 else None
    return {'input': original, 'institution_type': institution,
            'state': 'resolved' if resolved else ('ambiguous' if candidates else 'unresolved'),
            'normalized': resolved['name'] if resolved else '',
            'council_id': resolved['council_id'] if resolved else '',
            'candidates': candidates, 'source': data['source_url'], 'checked_at': data['checked_at'],
            'validity': 'dated_source_registry_not_legal_administrative_boundary_verification'}


def same_jurisdiction(left: str, right: str) -> bool:
    a, b = _compact(left), _compact(right)
    if not a or not b:
        return False
    la, rb = resolve_jurisdiction(left), resolve_jurisdiction(right)
    if 'ambiguous' in {la['state'], rb['state']}:
        return False
    if la['state'] == rb['state'] == 'resolved':
        return la['council_id'] == rb['council_id']
    return a == b
