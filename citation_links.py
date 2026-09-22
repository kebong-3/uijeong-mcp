"""Resolve human-readable official links without inventing URLs or source proof."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import re
import time
from urllib.parse import parse_qs, urlsplit

import evidence_core as E

SITE = 'https://www.gjsc.or.kr'


def viewer_key(url):
    try:
        p = urlsplit(url or '')
        q = parse_qs(p.query)
        if (p.scheme == 'https' and p.hostname in ('www.gjsc.or.kr', 'gjsc.or.kr')
                and not p.username and not p.password and p.port in (None, 443)
                and p.path in ('/record/recordView.do', '/record/originalDownload.do')
                and set(q) == {'key'} and len(q['key']) == 1
                and re.fullmatch(r'[A-Za-z0-9]{1,128}', q['key'][0])):
            return q['key'][0]
    except (ValueError, TypeError):
        pass
    return None


def set_link(record, url=None, status='UNRESOLVED', kind=None, reason=None):
    meta = record['metadata']
    date = meta.get('meeting_date') or ''
    if re.fullmatch(r'\d{8}', date):
        date = f'{date[:4]}.{date[4:6]}.{date[6:]}.'
    label = ' '.join(x for x in (date, meta.get('meeting_name'), '회의록 원문') if x)
    label = re.sub(r'[\[\]<>\r\n]', '', label)
    safe = E._safe_reference(url)
    markdown = f'[{label}]({safe})' if safe else None
    link = {'url': safe, 'label': label, 'markdown': markdown, 'status': status,
            'kind': kind, 'reason': reason}
    record['source_link'] = link
    record['provenance'].update(citation_url=safe, citation_markdown=markdown,
                                citation_status=status, citation_kind=kind)
    return link


def _meeting_name(value):
    return E.normalize_match(re.sub(r'행정사무감사|행정사무조사', '', value or ''))


def same_meeting(row, meta):
    if row.get('date') != meta.get('meeting_date'):
        return False
    if _meeting_name(row.get('mtgnm')) != _meeting_name(meta.get('meeting_name')):
        return False
    for a, b in (('numpr', 'term'), ('sesn', 'session'), ('odr', 'sitting')):
        left, right = str(row.get(a) or ''), str(meta.get(b) or '')
        # Audit records have CLIK session=year and sitting=0.
        if a == 'sesn' and re.fullmatch(r'20\d{2}', right):
            continue
        if left not in ('', '?', '0') and right not in ('', '?', '0') and left != right:
            return False
    return True


def body_matches(expected, actual):
    def value(t):
        return (E.normalize_match(t.get('label', '')), E.normalize_match(t.get('text', '')))
    target = {value(t) for t in actual}
    # Long, complete speeches distinguish the record from generic openings.
    anchors = sorted({value(t) for t in expected if len(E.normalize_match(t.get('text', ''))) >= 80},
                     key=lambda t: len(t[1]), reverse=True)[:3]
    return len(anchors) >= 2 and all(anchor in target for anchor in anchors)


class OfficialLinkResolver:
    def __init__(self, site):
        self.site = site
        self.cache = OrderedDict()

    async def candidates(self, meta):
        """Find the date in the descending official index with bounded page reads."""
        date = meta.get('meeting_date') or ''
        if not re.fullmatch(r'\d{8}', date):
            return []
        pages = {}
        async def page(n):
            if n not in pages:
                if len(pages) >= 14:
                    return []
                pages[n] = await self.site.list_page(n)
            return pages[n]
        def span(rows):
            dates = [r.get('date', '') for r in rows]
            if not dates or any(not re.fullmatch(r'\d{8}', d) for d in dates):
                return None
            if dates != sorted(dates, reverse=True):
                return None
            return dates[0], dates[-1]
        low, high, found = 1, 1, None
        while high <= 1024:
            rows = await page(high)
            bounds = span(rows)
            if bounds and bounds[0] >= date >= bounds[1]:
                found = high
                break
            if not rows or not bounds or bounds[1] <= date:
                break
            low, high = high + 1, high * 2
        while found is None and low <= high and len(pages) < 14:
            mid = (low + high) // 2
            rows = await page(mid)
            bounds = span(rows)
            if not rows:
                high = mid - 1
            elif not bounds:
                break
            elif bounds[0] >= date >= bounds[1]:
                found = mid
                break
            elif date > bounds[0]:
                high = mid - 1
            else:
                low = mid + 1
        if found:
            # A meeting date may straddle a page boundary.
            bounds = span(pages[found])
            if bounds[0] == date and found > 1:
                await page(found - 1)
            if bounds[1] == date:
                await page(found + 1)
        unique = {row['key']: row for rows in pages.values() for row in rows
                  if row.get('key') and same_meeting(row, meta)}
        return list(unique.values())

    async def resolve(self, record):
        provenance = record['provenance']
        original = provenance.get('source_url')
        if original:
            set_link(record, original, provenance.get('source_url_status', 'PROVIDED_NOT_FETCHED'),
                     'OFFICIAL_SOURCE')
        else:
            set_link(record, reason='공식 원문 링크를 아직 확인하지 못했습니다.')
        if record.get('source') == 'SEOGU_SITE':
            return set_link(record, original, 'FETCHED', 'OFFICIAL_VIEWER')
        meta = record['metadata']
        if meta.get('council_id') != '062006' or not str(record.get('docid', '')).startswith('CLIK'):
            return record['source_link']
        cache_key = (E._meeting_identity(record), record['body_sha256'])
        cached = self.cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 3600:
            return set_link(record, cached[1], 'FETCHED_MATCHED', 'OFFICIAL_VIEWER')
        key = viewer_key(original)
        candidates = [{'key': key}] if key else await self.candidates(meta)
        verified = []
        for row in candidates[:3]:
            doc = await self.site.detail(row['key'])
            if body_matches(record['turns'], doc.get('turns', [])):
                # Link copied from the fetched document, not from a guessed docid.
                if viewer_key(doc.get('url')) == row['key']:
                    verified.append(doc['url'])
        if len(verified) == 1:
            url = verified[0]
            self.cache[cache_key] = (time.monotonic(), url)
            self.cache.move_to_end(cache_key)
            while len(self.cache) > 256:
                self.cache.popitem(last=False)
            return set_link(record, url, 'FETCHED_MATCHED', 'OFFICIAL_VIEWER')
        record['source_link']['reason'] = ('공식 목록에서 일치하는 회의 후보를 찾지 못했습니다.' if not candidates
            else '공식 본문과의 일치 또는 단일 회의 식별을 확인하지 못했습니다.')
        return record['source_link']

    async def enrich(self, records, timeout=25):
        # A slow link lookup must not discard already fetched meeting evidence.
        for record in records:
            p = record['provenance']
            set_link(record, p.get('source_url'), p.get('source_url_status', 'UNRESOLVED'),
                     'OFFICIAL_SOURCE' if p.get('source_url') else None)
        try:
            async with asyncio.timeout(timeout):
                for record in records:
                    try:
                        await self.resolve(record)
                    except Exception as exc:
                        record['source_link']['reason'] = '원문 링크 확인 실패: ' + type(exc).__name__
        except TimeoutError:
            for record in records:
                if record['source_link']['status'] not in ('FETCHED', 'FETCHED_MATCHED'):
                    record['source_link']['reason'] = '링크 확인 시간 한도 도달. 본문 조회 결과는 유지했습니다.'
