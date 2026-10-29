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
        headers = {"accept": "application/json, text/event-stream"}

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
