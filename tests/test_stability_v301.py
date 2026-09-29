"""Stability-focused v3.0.1 tests: CLIK-only council retrieval and connection headroom."""
import asyncio
import os

import pytest
import runtime_security as R
import public_server as P
import sources as S
import uijeong_mcp as U


def test_seogu_direct_adapter_disabled_in_registry():
    result=S.search_sources("광주 서구", direct_only=True)
    assert result["status"]=="EMPTY"
    assert result["total_matches"]==0


def test_site_source_is_rejected_before_network():
    result=asyncio.run(U.council_evidence_bundle(keyword="휴라운지",council="광주 서구",source="site"))
    assert result["status"]=="INVALID_INPUT"
    assert "홈페이지 직접 검색" in result["message"]


def test_site_ref_is_rejected_before_network():
    result=asyncio.run(U.council_read_source(ref="site:abcdef"))
    assert result["status"]=="INVALID_INPUT"
    assert "직접 조회는 제거" in result["message"]


def test_status_reports_clik_only_without_live_network():
    result=asyncio.run(U.council_status(live=False))
    assert result["direct_adapters"]==["CLIK"]
    assert "SEOGU_SITE" in result["disabled_adapters"]
    assert result["capacity"]["transport_max_concurrent"]==8
    assert result["capacity"]["tool_max_concurrent"]==3
    assert result["capacity"]["public_requests_per_minute"]==360


def test_secure_public_transport_has_rollout_headroom(monkeypatch):
    monkeypatch.setenv("UIJEONG_AUTH_MODE","public")
    monkeypatch.setenv("UIJEONG_PUBLIC_READONLY","true")
    monkeypatch.setenv("UIJEONG_BIND_HOST","0.0.0.0")
    monkeypatch.setenv("UIJEONG_ALLOWED_HOSTS","mcp.example.test")
    async def inner(scope,receive,send):
        await R._public_reply(send,200,{"ok":True})
    inner.uijeong_public_readonly=True
    app=R.secure_http_app(inner)
    assert app.requests_per_minute==360
    assert app.app.max_concurrent==8
    assert app.app.max_waiting==40


def test_heavy_tool_execution_still_capped_at_three():
    active=0
    peak=0
    entered=asyncio.Event()
    release=asyncio.Event()
    async def tool(query:str="x")->dict:
        nonlocal active,peak
        active+=1
        peak=max(peak,active)
        if peak==3:
            entered.set()
        await release.wait()
        active-=1
        return {"status":"COMPLETE"}

    wrapped=P.public_function(tool)
    async def run():
        tasks=[asyncio.create_task(wrapped(query=str(i))) for i in range(5)]
        await asyncio.wait_for(entered.wait(),1)
        await asyncio.sleep(.02)
        assert peak==3
        release.set()
        rows=await asyncio.gather(*tasks)
        assert all(x["status"]=="COMPLETE" for x in rows)
    asyncio.run(run())
