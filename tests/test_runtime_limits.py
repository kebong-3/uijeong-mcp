"""작은 인스턴스에서 오래 돌 때의 메모리·응답성 보호 검사.

캐시는 같은 회의록을 다시 받지 않기 위한 것이지 보관소가 아니다. 상한이 없으면
회의록을 열수록 메모리가 늘고, 512MB급 인스턴스에서는 프로세스가 상태점검에
응답하지 못해 배포 실패로 처리된다.
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uijeong_mcp as U


def test_trim_cache_drops_oldest_quarter_at_limit():
    cache = {f'k{i}': (float(i), i) for i in range(20)}
    U._trim_cache(cache, 20)
    assert len(cache) == 15
    assert 'k0' not in cache and 'k4' not in cache, '가장 오래된 항목부터 비운다'
    assert 'k5' in cache and 'k19' in cache


def test_trim_cache_leaves_room_below_limit():
    cache = {'a': (1.0, 1)}
    U._trim_cache(cache, 20)
    assert cache == {'a': (1.0, 1)}


@pytest.mark.parametrize('limit', [1, 2, 3])
def test_trim_cache_always_frees_at_least_one_slot(limit):
    cache = {f'k{i}': (float(i), i) for i in range(limit)}
    U._trim_cache(cache, limit)
    assert len(cache) < limit


def test_cache_limits_are_bounded_and_tunable():
    assert 20 <= U.CACHE_MAX <= 2000
    assert 10 <= U.SITE_DETAIL_CACHE_MAX <= 2000
    assert U.SITE_LIST_CACHE_MAX >= 10


def test_site_detail_cache_does_not_grow_without_bound(monkeypatch):
    site = U.CouncilSite()
    body = ('<b>○김가상 위원</b> 급식 점검은 어떻게 합니까?<br>'
            '<b>○노인복지과장 이가상</b> 분기마다 점검합니다.<br>')

    async def fake_get(url):
        return body

    monkeypatch.setattr(site, 'get', fake_get)
    monkeypatch.setattr(U, 'SITE_DETAIL_CACHE_MAX', 8)

    async def run():
        for i in range(30):
            await site.detail(f'key{i:04d}')

    asyncio.run(run())
    assert len(site._detail_cache) <= 8, '회의록을 계속 열어도 캐시는 한도 안에 머문다'


def test_minute_parsing_does_not_block_the_event_loop(monkeypatch):
    """파싱 중에도 다른 작업이 진행돼야 한다. 멈추면 상태점검이 밀린다."""
    site = U.CouncilSite()
    body = '<b>○김가상 위원</b> 급식 점검 계획을 밝혀 주십시오. 예산은 얼마입니까?<br>' * 3000

    async def fake_get(url):
        return body

    monkeypatch.setattr(site, 'get', fake_get)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    async def run():
        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.005)
        before = ticks
        await site.detail('doclong')          # 한 건이 수십 밀리초 걸리는 긴 회의록
        during = ticks - before
        beat.cancel()
        return during

    during = asyncio.run(run())
    # 파싱을 이벤트 루프에서 직접 실행하면 heartbeat가 0회다.
    # CI 러너 속도·스케줄러에 따라 tick 절대 횟수는 흔들리므로,
    # 실제로 다른 작업이 진행됐다는 사실만 검증한다.
    assert during >= 1, f'파싱 중에도 다른 작업이 진행돼야 한다(진행 {during}회)'
