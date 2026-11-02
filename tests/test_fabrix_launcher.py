"""Exercise the actual entry file over TCP, without Render or upstream API keys."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "fabrix_server.py"


def clean_environment(tmp_path):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("UIJEONG_", "FABRIX_")) and key not in {
               "PORT", "CLIK_API_KEY", "LAW_OC", "LOFIN_API_KEY", "FINANCE365_SERVICE_KEY",
               "DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_SEARCH_KEY", "KOSIS_API_KEY"}}
    env.update(UIJEONG_STATE_DB=str(tmp_path / "state.sqlite3"), PYTHONUNBUFFERED="1")
    return env


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def launched(tmp_path, env, port, host):
    # Start from another directory, as a repository deployment runner may do.
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, str(SCRIPT)], cwd=tmp_path,
                                   env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                              headers={"host": host}, timeout=5) as client:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        pytest.fail("Launcher exited before readiness: " + log.read())
                    try:
                        response = client.get("/healthz")
                        if response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    if time.monotonic() >= deadline:
                        log.seek(0)
                        pytest.fail("Launcher readiness timed out: " + log.read())
                    time.sleep(0.05)
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("custom_gateway", [False, True])
def test_entrypoint_public_protocol_and_gateway_boundaries(tmp_path, custom_gateway):
    env = clean_environment(tmp_path)
    port = free_port() if custom_gateway else 8080
    host = "fabrix.example.test" if custom_gateway else f"127.0.0.1:{port}"
    if custom_gateway:
        env.update(PORT=str(port), FABRIX_SERVER_URL="https://fabrix.example.test/mcp")
    with launched(tmp_path, env, port, host) as client:
        # JSON-only clients keep the existing one-response behavior.
        headers = {"accept": "application/json"}

        def rpc(method, params):
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            assert response.status_code == 200, response.text
            assert "error" not in response.json(), response.text
            return response.json()["result"]

        initialized = rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                         "clientInfo": {"name": "fabrix-launcher-test", "version": "1"}})
        assert initialized["protocolVersion"]
        tools = rpc("tools/list", {})["tools"]
        names = {row["name"] for row in tools}
        assert len(names) == 40
        assert {"council_find_council", "budget_calculate", "ordinance_guide"} <= names
        assert all(row["annotations"]["readOnlyHint"] for row in tools)
        for name, arguments in [
            ("council_find_council", {"query": "광주 서구"}),
            ("budget_calculate", {"operation": "change", "arguments": {
                "before": "100", "after": "120", "unit": "천원"}}),
            ("ordinance_guide", {}),
        ]:
            result = rpc("tools/call", {"name": name, "arguments": arguments})
            assert not result.get("isError"), result
        # FabriX-style Streamable HTTP clients advertise both media types.
        # The server should answer these requests as a finite SSE response stream,
        # including direct stateless tool calls used by connection health checks.
        def sse_payload(response):
            assert response.status_code == 200, response.text
            assert response.headers["content-type"].startswith("text/event-stream")
            rows = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
            assert rows, response.text
            return json.loads(rows[-1])

        sse_headers = {"accept": "application/json, text/event-stream"}
        hybrid_init = client.post("/mcp", headers=sse_headers, json={
            "jsonrpc": "2.0", "id": 101, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "fabrix-healthcheck-test", "version": "1"}}})
        assert hybrid_init.status_code == 200, hybrid_init.text
        hybrid_session = hybrid_init.headers.get("mcp-session-id")
        assert hybrid_session
        hybrid_payload = hybrid_init.json()
        protocol = hybrid_payload["result"]["protocolVersion"]
        hybrid_headers = {
            "accept": "application/json",
            "mcp-session-id": hybrid_session,
            "mcp-protocol-version": protocol,
        }
        hybrid_tools = client.post("/mcp", headers=hybrid_headers, json={
            "jsonrpc": "2.0", "id": 103, "method": "tools/list", "params": {}})
        assert hybrid_tools.status_code == 200, hybrid_tools.text
        assert len(hybrid_tools.json()["result"]["tools"]) == 40
        # Standalone server-push GET is optional in MCP 2025-11-25. For FabriX
        # compatibility it must terminate immediately with the spec-defined 405
        # instead of holding an idle SSE stream open until the platform timeout.
        hybrid_get = client.get("/mcp", headers=hybrid_headers)
        assert hybrid_get.status_code == 405, hybrid_get.text
        assert "POST" in hybrid_get.headers.get("allow", "")

        # A direct no-session tool call still takes the legacy/stateless SSE path.
        called_sse = sse_payload(client.post("/mcp", headers=sse_headers, json={
            "jsonrpc": "2.0", "id": 102, "method": "tools/call",
            "params": {"name": "council_find_council", "arguments": {"query": "광주 서구"}}}))
        assert not called_sse["result"].get("isError", False)

        # FabriX dedicated endpoint is stateful and must issue a session ID.
        stateful_init = client.post("/mcp-fabrix", headers=sse_headers, json={
            "jsonrpc": "2.0", "id": 201, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "fabrix-stateful-test", "version": "1"}}})
        init_payload = sse_payload(stateful_init)
        session_id = stateful_init.headers.get("mcp-session-id")
        assert session_id
        protocol = init_payload["result"]["protocolVersion"]
        stateful_headers = {
            **sse_headers,
            "mcp-session-id": session_id,
            "mcp-protocol-version": protocol,
        }
        notified = client.post("/mcp-fabrix", headers=stateful_headers, json={
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        assert notified.status_code == 202, notified.text
        tools_payload = sse_payload(client.post("/mcp-fabrix", headers=stateful_headers, json={
            "jsonrpc": "2.0", "id": 202, "method": "tools/list", "params": {}}))
        assert len(tools_payload["result"]["tools"]) == 40
        deleted = client.delete("/mcp-fabrix", headers=stateful_headers)
        assert deleted.status_code == 200, deleted.text
        expired = client.post("/mcp-fabrix", headers=stateful_headers, json={
            "jsonrpc": "2.0", "id": 203, "method": "tools/list", "params": {}})
        assert expired.status_code == 404, expired.text

        forbidden = rpc("tools/call", {"name": "council_search_local", "arguments": {"keyword": "x"}})
        assert forbidden.get("isError")
        assert client.get("/healthz", headers={"host": "untrusted.example.test"}).status_code == 403
        assert client.get("/healthz", headers={"origin": "https://untrusted.example.test"}).status_code == 403
        assert client.post("/mcp", content=b"x" * 65537).status_code == 413
        assert client.get("/mcp").status_code == 405


def test_check_uses_real_sdk_without_keys(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=tmp_path,
                            env=clean_environment(tmp_path), capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["port"] == 8080
    assert report["public_protocol"]["status"] == "PASS"
    assert report["public_protocol"]["network_called"] is False


@pytest.mark.parametrize("overrides", [
    {"PORT": "not-a-port"},
    {"PORT": "65536"},
    {"UIJEONG_AUTH_MODE": "bearer"},
    {"UIJEONG_PUBLIC_READONLY": "false"},
    {"UIJEONG_ALLOWED_HOSTS": "*"},
    {"FABRIX_SERVER_URL": "https://user:synthetic-password@example.test/mcp"},
])
def test_invalid_deployment_configuration_fails_clearly(tmp_path, overrides):
    env = clean_environment(tmp_path)
    env.update(overrides)
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0
    assert "synthetic-password" not in result.stderr
    assert "\"status\": \"PASS\"" not in result.stdout
