"""Offline tests for public listing, legal and domain-verification routes."""
import asyncio
import os
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_site as P
import runtime_security as R


def test_public_pages_are_html_and_named():
    for path in ("/", "/about", "/privacy", "/terms", "/support"):
        status, content_type, body = P.route(path, "GET")
        assert status == 200
        assert content_type.startswith(b"text/html")
        text = body.decode("utf-8")
        assert "지방의회·예산·조례 MCP" in text
        assert "전남광주통합특별시 서구청 펀온워크 AI혁신분과 에이블(AIBLE)" in text


def test_challenge_returns_exact_token(monkeypatch):
    monkeypatch.setenv("OPENAI_APPS_CHALLENGE", "challenge-token-ABC123")
    status, content_type, body = P.route("/.well-known/openai-apps-challenge", "GET")
    assert status == 200
    assert content_type == b"text/plain; charset=utf-8"
    assert body == b"challenge-token-ABC123"
    assert not body.endswith(b"\n")


def test_challenge_unconfigured_is_not_fake_success(monkeypatch):
    monkeypatch.delenv("OPENAI_APPS_CHALLENGE", raising=False)
    status, _, body = P.route("/.well-known/openai-apps-challenge", "GET")
    assert status == 404
    assert body == b"Not configured"


@pytest.fixture
def env(monkeypatch):
    for name in list(os.environ):
        if name.startswith("UIJEONG_") or name in ("PORT", "OPENAI_APPS_CHALLENGE"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UIJEONG_AUTH_MODE", "public")
    monkeypatch.setenv("UIJEONG_PUBLIC_READONLY", "true")
    monkeypatch.setenv("UIJEONG_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("UIJEONG_ALLOWED_HOSTS", "mcp.example.test")
    monkeypatch.setenv("OPENAI_APPS_CHALLENGE", "verify-me")


def test_http_guard_serves_pages_before_mcp_boundary(env):
    async def inner(scope, receive, send):
        raise AssertionError("public static page must not reach MCP app")
    inner.uijeong_public_readonly = True
    app = R.HTTPGuard(inner)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="https://mcp.example.test",
        ) as client:
            root = await client.get("/")
            assert root.status_code == 200
            assert "지방의회·예산·조례 MCP" in root.text
            privacy = await client.get("/privacy")
            assert privacy.status_code == 200
            challenge = await client.get("/.well-known/openai-apps-challenge")
            assert challenge.status_code == 200
            assert challenge.text == "verify-me"
            assert challenge.headers["content-type"].startswith("text/plain")
    asyncio.run(run())
