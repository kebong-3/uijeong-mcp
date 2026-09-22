"""Real installed MCP SDK + subprocess stdio and TCP Streamable HTTP smoke test.

No fake SDK, no external API, no real authentication key; fail on missing deps.
Run from project root: python tests/protocol_smoke.py
"""
from __future__ import annotations
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]


def environment(state: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in ("UIJEONG_ALLOWED_HOSTS", "UIJEONG_ALLOWED_ORIGINS", "UIJEONG_BEARER_TOKEN", "UIJEONG_DATA_DIR"):
        env.pop(key, None)
    for key in list(env):
        if key.startswith("UIJEONG_OAUTH_") or key in ("UIJEONG_AUTH_MODE", "UIJEONG_RESOURCE_URL"):
            env.pop(key, None)
    env.update(CLIK_API_KEY="", UIJEONG_PROFILE="full", UIJEONG_STATE_DB=state,
               UIJEONG_BIND_HOST="127.0.0.1", PYTHONUNBUFFERED="1")
    return env


async def inspect_session(session: ClientSession) -> dict:
    initialized = await session.initialize()
    listed = await session.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert "council_evidence_bundle" in tools
    assert "snapshot_id" in tools["council_evidence_bundle"].inputSchema["properties"]
    assert "live" in tools["council_status"].inputSchema["properties"]
    status = await session.call_tool("council_status", {"live": False})
    assert not status.isError
    assert isinstance(status.structuredContent, dict), "Actual MCP structuredContent is missing"
    state = status.structuredContent
    assert state["status"] == "COMPLETE" and state["clik_key_configured"] is False
    assert state["release_verification"]["status"] == "MATCH"
    assert state["budget"]["attempted_calls"] == 0 and state["live_checks"] == []
    bad = await session.call_tool("council_evidence_bundle", {
        "keyword": "성인지예산", "date_from": "2026-09-17", "date_to": "2023-09-17"})
    assert bad.isError, "INVALID_INPUT must propagate as MCP isError"
    assert bad.structuredContent["status"] == "INVALID_INPUT"
    unavailable = await session.call_tool("council_evidence_bundle", {
        "keyword": "성인지예산", "council": "051001", "source": "clik", "max_docs": 1})
    assert unavailable.isError, "Missing API key must propagate as MCP isError"
    assert unavailable.structuredContent["status"] == "ERROR"
    analyzed = await session.call_tool("council_analyze_text", {
        "minutes_text": "합성 시험자료\n○가상위원 김가상: 예산 산출근거가 무엇입니까?\n○기획과장 이가상: 자료를 제출하겠습니다.",
        "source_kind": "합성·시험"})
    serialized = json.dumps(analyzed.model_dump(mode="json"), ensure_ascii=False)
    assert "SYNTHETIC" in serialized and not analyzed.isError
    assert "council_plan_session" in tools and "council_review_followups" in tools
    planned = await session.call_tool("council_plan_session", {"department":"기획실", "topics":["성인지예산"], "meeting_type":"예산심사"})
    assert not planned.isError and planned.structuredContent["stored"] is False
    reviewed = await session.call_tool("council_review_answer", {"draft":"반드시 전액 지원하겠습니다."})
    assert not reviewed.isError and reviewed.structuredContent["ready_for_submission"] is False
    figures = await session.call_tool("council_check_figures", {"data":[{"name":"합성사업", "unit":"천원", "current":120,"previous":100}]})
    assert figures.structuredContent["items"][0]["change"]=="20"
    invalid_work = await session.call_tool("council_review_followups", {"snapshot_id":"not-a-real-snapshot", "updates":[], "as_of":"2026-09-19"})
    assert invalid_work.isError
    resources = await session.list_resources()
    assert 'uijeong://guide/answer-preparation' in {str(r.uri) for r in resources.resources}
    guide = await session.read_resource('uijeong://guide/answer-preparation')
    assert 'council_audit_claims' in guide.contents[0].text
    prompts = await session.list_prompts()
    assert '근거기반_의회답변' in {p.name for p in prompts.prompts}
    assert {"council_prepare_response", "council_audit_claims", "council_compare_metrics", "council_compare_evidence"} <= set(tools)
    audit = await session.call_tool("council_audit_claims", {"draft":"합성자료 100명", "claims":[], "as_of":"2026-09-20"})
    assert not audit.isError and audit.structuredContent["unlinked_span_count"] == 1
    assert audit.structuredContent["ready_for_submission"] is False
    bad_preparation = await session.call_tool("council_prepare_response", {
        "topic":"합성사업", "department":"합성부서", "date_from":"2026-09-20", "date_to":"2024-01-01"})
    assert bad_preparation.isError and bad_preparation.structuredContent["status"] == "INVALID_INPUT"
    base = dict(unit="천원", metric="합성사업비", entity="합성부서", population="전체", period_basis="연간", accounting_basis="최종예산", document_ref="합성문서")
    checked = await session.call_tool("council_compare_metrics", {"data":[{"name":"합성사업", "previous":dict(base, value=100, fiscal_year=2025), "current":dict(base, value=120, fiscal_year=2026)}]})
    assert checked.structuredContent["items"][0]["calculation"]["delta"] == "20000"
    bad_pair = await session.call_tool("council_compare_evidence", {"snapshot_ids":[], "pairs":[]})
    assert bad_pair.isError
    return {"protocol": initialized.protocolVersion, "tool_count": len(tools),
            "response_tools_v250": True, "resources_and_prompt": True, "runtime_manifest_match": True, "workbench_tools": True, "structured_content": True, "invalid_input_is_error": True, "missing_key_is_error": True,
            "synthetic_provenance": True}


async def stdio_check(temp: str) -> dict:
    parameters = StdioServerParameters(command=sys.executable, args=[str(ROOT / "uijeong_mcp.py")],
                                       cwd=str(ROOT), env=environment(str(Path(temp) / "stdio.sqlite3")))
    with open(Path(temp) / "stdio.stderr", "w+") as errlog:
        async with stdio_client(parameters, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                return await inspect_session(session)


async def http_check(temp: str) -> dict:
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    token = "protocol-smoke-synthetic-bearer-token-only"
    env = environment(str(Path(temp) / "http.sqlite3"))
    env.update(PORT=str(port), UIJEONG_BEARER_TOKEN=token)
    url = f"http://127.0.0.1:{port}/mcp"
    with open(Path(temp) / "http.stderr", "w+") as errlog:
        process = subprocess.Popen([sys.executable, str(ROOT / "uijeong_mcp.py"), "--http"], cwd=ROOT,
                                   env=env, stdout=errlog, stderr=errlog)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        errlog.seek(0)
                        raise AssertionError("HTTP subprocess startup failed: " + errlog.read()[-3000:])
                    try:
                        response = await client.get(url)
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.1)
                else:
                    raise AssertionError("HTTP startup timed out")
                assert response.status_code == 401
                assert (await client.post(url, headers={"host": "evil.example"})).status_code == 403
                assert (await client.post(url, headers={"origin": "https://evil.example", "authorization": "Bearer " + token})).status_code == 403
                assert (await client.post(url, headers={"authorization": "Bearer " + token}, content=b"x" * (1024 * 1024 + 1))).status_code == 413
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False) as client:
                async with streamable_http_client(url, http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        result = await inspect_session(session)
                        result.update(unauthorized_401=True, foreign_host_403=True, foreign_origin_403=True, large_request_413=True)
                        return result
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="uijeong-protocol-") as temp:
        result = {"sdk_version": version("mcp"), "real_sdk": True, "external_api_calls": 0,
                  "stdio": await stdio_check(temp), "streamable_http": await http_check(temp)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
