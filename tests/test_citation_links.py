"""Regression cases for real 2026-09-22 failures; all network inputs are fixtures."""
import asyncio
import copy
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import citation_links as L
import evidence_core as E
import public_server as P
import response_budget as B
import runtime_security as R

KEY = 'ab12' * 22
VIEW = L.SITE + '/record/recordView.do?key=' + KEY
DOWNLOAD = L.SITE + '/record/originalDownload.do?key=' + KEY
BODY = ('○김가상 위원: ' + '오잇길 사업의 구체적인 계획과 예산 근거를 설명해 주시기 바랍니다. ' * 5
        + '\n○복지정책과장 이가상: ' + '주민 의견을 수렴하고 담당 부서와 협의하여 관련 자료를 제출하겠습니다. ' * 5)


def record(url=None):
    return E.make_record(dict(DOCID='CLIKTEST1', RASMBLY_ID='062006', RASMBLY_NUMPR='9',
        RASMBLY_SESN='2025', MINTS_ODR='0', MTG_DE='20251202', MTGNM='사회도시위원회'),
        E.parse_turns(BODY), source='CLIK', source_url=url,
        body_url='https://clik.nanet.go.kr/openapi/minutes.do', body_url_verified=True)


class Site:
    def __init__(self, mismatch=False):
        self.calls = []
        self.mismatch = mismatch
    async def list_page(self, page):
        self.calls.append(('list', page))
        if page > 10:
            return []
        date = '20260101' if page < 7 else ('20251202' if page == 7 else '20251101')
        return [{'key':KEY if page == 7 else f'key{page}', 'date':date,
                 'mtgnm':'사회도시위원회', 'numpr':'9', 'sesn':'', 'odr':''}]
    async def detail(self, key):
        self.calls.append(('detail', key))
        return {'url':L.SITE + '/record/recordView.do?key=' + key,
                'turns':E.parse_turns('○기획과장 이가상: 다른 회의입니다.' if self.mismatch else BODY)}


def test_public_record_key_survives_all_output_shapes(monkeypatch):
    monkeypatch.setenv('CLIK_API_KEY', 'test-api-secret')
    payload = {'url':VIEW, 'markdown':f'[회의록 원문]({VIEW})',
               'json':f'{{"url":"{VIEW}"}}', 'secret':'test-api-secret',
               'api':'https://clik.nanet.go.kr/openapi/minutes.do?key=other-secret'}
    scrubbed=P._scrub(payload)
    assert scrubbed['url'] == VIEW and VIEW in scrubbed['markdown'] and VIEW in scrubbed['json']
    assert 'test-api-secret' not in str(scrubbed) and 'other-secret' not in str(scrubbed)


@pytest.mark.parametrize('url', [
    'https://evil.test/record/recordView.do?key=secret',
    'https://www.gjsc.or.kr.evil.test/record/recordView.do?key=secret',
    'https://www.gjsc.or.kr/other?key=secret',
    'https://www.gjsc.or.kr/record/recordView.do?key=secret&token=credential',
    'https://www.gjsc.or.kr/record/recordView.do?key=secret&key=other',
    'https://user@www.gjsc.or.kr/record/recordView.do?key=secret',
])
def test_only_exact_public_record_urls_are_exempt(url):
    assert 'secret' not in R.redact_secrets(url)


def test_known_secret_is_never_exempt_even_in_official_url(monkeypatch):
    monkeypatch.setenv('CLIK_API_KEY', KEY)
    assert KEY not in R.redact_secrets(VIEW)


def test_missing_link_resolves_from_official_index_and_body():
    site=Site(); resolver=L.OfficialLinkResolver(site); item=record()
    asyncio.run(resolver.enrich([item]))
    link=item['source_link']
    assert link['url']==VIEW and link['status']=='FETCHED_MATCHED'
    assert '2025.12.02.' in link['markdown']
    assert item['provenance']['source_url'] is None  # Preserve actual CLIK provenance.
    citation=E.turn_evidence(item,item['turns'][0])['citation']
    assert citation['citation_url']==VIEW
    before=len(site.calls)
    asyncio.run(resolver.enrich([copy.deepcopy(item)]))
    assert len(site.calls)==before


def test_attachment_resolves_to_verified_html():
    site=Site(); item=record(DOWNLOAD)
    asyncio.run(L.OfficialLinkResolver(site).enrich([item]))
    assert item['source_link']['url']==VIEW
    assert site.calls==[('detail', KEY)]


def test_wrong_body_is_not_linked():
    item=record()
    asyncio.run(L.OfficialLinkResolver(Site(mismatch=True)).enrich([item]))
    assert item['source_link']['url'] is None


def test_timeout_preserves_evidence_and_marks_unverified():
    class Slow(Site):
        async def list_page(self, page): await asyncio.sleep(1)
    item=record(); body=copy.deepcopy(item['turns'])
    asyncio.run(L.OfficialLinkResolver(Slow()).enrich([item],timeout=0.001))
    assert item['turns']==body and item['source_link']['url'] is None
    assert '시간 한도' in item['source_link']['reason']


@pytest.mark.parametrize('role',['위원장직무대리','의장직무대리','임시위원장','부위원장'])
def test_acting_chair_boundary_and_attribution(role):
    turns=E.parse_turns(f'<b>○건강증진과장 이은주</b>예.<br>○{role} 임성화  질의를 종결합니다.<br>○김수영 위원  오잇길 계획은 무엇인가요?')
    assert [t['role'] for t in turns]==['executive','chair','member']
    assert turns[0]['text']=='예.' and turns[1]['label']==role+' 임성화'
    assert turns[0]['agenda'] != turns[2]['agenda']


def test_digest_keeps_clickable_citation():
    item=record(VIEW); L.set_link(item,VIEW,'FETCHED_MATCHED','OFFICIAL_VIEWER')
    event=E.record_events(item,'오잇길','질의답변')[0]
    assert f']({VIEW})' in B.digest({'status':'COMPLETE','items':[event]})
    assert f']({VIEW})' in B.digest({'status':'COMPLETE','source_link':item['source_link']})


def test_queue_timeout_and_cancellation_release_capacity():
    async def run():
        entered=asyncio.Event(); release=asyncio.Event()
        async def inner(scope,receive,send):
            entered.set(); await release.wait(); await R._public_reply(send,200,{'ok':True})
        app=R.PublicBoundary(inner,max_concurrent=1,max_waiting=1,queue_timeout=.05)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://test') as c:
            first=asyncio.create_task(c.post('/mcp',json={}))
            await entered.wait()
            timeout=await c.post('/mcp',json={})
            assert timeout.status_code==503 and timeout.json()['error']=='PUBLIC_QUEUE_TIMEOUT'
            queued=asyncio.create_task(c.post('/mcp',json={}))
            await asyncio.sleep(.005)
            overflow=await c.post('/mcp',json={})
            assert overflow.status_code==503 and overflow.json()['error']=='PUBLIC_BUSY'
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):await queued
            assert app.waiting==0
            release.set(); assert (await first).status_code==200
            assert (await c.post('/mcp',json={})).status_code==200
            assert app.active==0 and app.waiting==0
    asyncio.run(run())


def site_list_html(key, date='2026.01.21'):
    return ('<a href="/kr/assembly/late.do?pageNum=2">2</a><table><tr>'
            '<td>1</td><td>9대</td><td>제337회</td><td>2차</td>'
            f'<td><a href="/record/recordView.do?key={key}">사회도시위원회</a></td>'
            f'<td>{date}</td></tr></table>')


def test_real_pagination_and_concurrent_cache_misses(monkeypatch):
    import uijeong_mcp as U
    async def run():
        site=U.CouncilSite(); calls=[]
        site._page_param='pageIndex'  # Recover a stale deployment setting.
        async def get(url):
            calls.append(url); await asyncio.sleep(.005)
            if '?' not in url:return site_list_html('first')
            assert url.endswith('?pageNum=2')
            return site_list_html('second', '2026.01.20')
        monkeypatch.setattr(site,'get',get)
        rows=await asyncio.gather(*(site.list_page(2) for _ in range(5)))
        assert all(r[0]['key']=='second' for r in rows)
        assert len(calls)==2
    asyncio.run(run())


def test_repeated_first_page_is_reported_as_failure(monkeypatch):
    import uijeong_mcp as U
    async def run():
        site=U.CouncilSite()
        async def get(url):return site_list_html('same')
        monkeypatch.setattr(site,'get',get)
        with pytest.raises(U.SiteBlocked) as exc:await site.list_page(16)
        assert exc.value.reason_code=='PAGINATION_NOT_ADVANCING'
        assert 16 not in site._list_cache
    asyncio.run(run())


def test_audit_title_and_detail_cache(monkeypatch):
    import uijeong_mcp as U
    async def run():
        site=U.CouncilSite(); calls=[]
        async def get(url):
            calls.append(url); await asyncio.sleep(.005)
            return '<title>2025년도 사회도시위원회 (2025.12.02.)</title><main>'+BODY+'</main>'
        monkeypatch.setattr(site,'get',get)
        docs=await asyncio.gather(*(site.detail(KEY) for _ in range(5)))
        assert len(calls)==1
        assert docs[0]['meta']==dict(sesn='2025',mtgnm='사회도시위원회',odr='0',date='20251202')
    asyncio.run(run())
