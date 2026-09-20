"""Security boundaries use controlled synthetic requests, never production abuse."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
import datetime as dt
import gzip
import os
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_security as S


def _reserve_many(args):
    path, count = args
    budget = S.SQLiteBudget(path, 37, scope="test")
    return sum(budget.reserve() for _ in range(count))


def test_budget_concurrent_processes_and_restart(tmp_path):
    path = tmp_path / "state.sqlite3"
    with ProcessPoolExecutor(max_workers=4) as pool:
        accepted = sum(pool.map(_reserve_many, [(str(path), 20)] * 4))
    assert accepted == 37
    restarted = S.SQLiteBudget(path, 37, scope="test")
    assert restarted.remaining() == 0
    assert restarted.reserve() is False
    assert restarted.status()["official_remaining"] is False
    assert S.SQLiteBudget(path, 37, scope="other-key").remaining() == 37


def test_budget_kst_midnight(tmp_path):
    clock = [dt.datetime(2026, 9, 17, 14, 59, 59, tzinfo=dt.timezone.utc).timestamp()]
    budget = S.SQLiteBudget(tmp_path / "state.sqlite3", 2, clock=lambda: clock[0])
    assert budget.reserve(2)
    assert budget.status()["day_kst"] == "2026-09-17"
    clock[0] += 1
    assert budget.status()["day_kst"] == "2026-09-18"
    assert budget.remaining() == 2


@pytest.mark.parametrize("cost", [True, 0, -1, 1.5, "1"])
def test_budget_bad_cost(tmp_path, cost):
    with pytest.raises(ValueError):
        S.SQLiteBudget(tmp_path / "s.db").reserve(cost)


def test_scope_is_key_hash_not_key():
    scope = S.key_scope("example-secret")
    assert "example-secret" not in scope
    assert scope == S.key_scope("example-secret")
    assert scope != S.key_scope("other-secret")


def test_snapshots_scope_restart_ttl_and_permissions(tmp_path):
    clock = [1000.0]
    path = tmp_path / "s.db"
    a = S.SnapshotStore(path, "org-a", clock=lambda: clock[0])
    ident = a.put({"quotation": "공개 합성 형식 시험"}, ttl_seconds=10, source_kind="OFFICIAL_FETCHED")
    assert S.SnapshotStore(path, "org-a", clock=lambda: clock[0]).get(ident)["quotation"]
    assert S.SnapshotStore(path, "org-b", clock=lambda: clock[0]).get(ident) is None
    assert path.stat().st_mode & 0o777 == 0o600
    clock[0] = 1010
    assert a.get(ident) is None


def test_snapshot_private_opt_in_and_bounds(tmp_path):
    a = S.SnapshotStore(tmp_path / "s.db", max_bytes=100, max_entries=1)
    with pytest.raises(S.SecurityError):
        a.put({"private": "사용자 원문"}, source_kind="USER_PROVIDED")
    with pytest.raises(S.SecurityError):
        a.put({"large": "한" * 100})
    ident = a.put({"public": "x"})
    with pytest.raises(S.SecurityError):
        a.put({"public": "y"})
    assert a.get(ident) == {"public": "x"}  # Unexpired cursors are not evicted.
    assert a.delete(ident)
    b = S.SnapshotStore(tmp_path / "s.db", "explicit-local", allow_private=True)
    assert b.get(b.put({"text": "입력"}, source_kind="USER_PROVIDED"))


@pytest.mark.parametrize("ident", ["", "a" * 63, "a" * 65, "../file", "' OR 1=1 --", None])
def test_snapshot_invalid_ids(tmp_path, ident):
    assert S.SnapshotStore(tmp_path / "s.db").get(ident) is None


@pytest.mark.parametrize("url", [
    "http://clik.nanet.go.kr/a", "https://clik.nanet.go.kr.evil.test/a",
    "https://evil.test@clik.nanet.go.kr/a", "https://clik.nanet.go.kr:444/a",
    "https://127.0.0.1/a", "file:///etc/passwd", "https://clik.nanet.go.kr/a#fragment",
    "https://clik.nanet.go.kr\\@evil.test/a", "https://clik.nanet.go.kr/\nx",
])
def test_destination_rejects(url):
    with pytest.raises(S.SecurityError):
        S.validate_url(url, ["clik.nanet.go.kr"])


def test_public_dns_rejects_mixed_resolution(monkeypatch):
    async def go():
        async def resolve(*args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
        with pytest.raises(S.SecurityError):
            await S._public_dns("clik.nanet.go.kr")
    asyncio.run(go())


def _network_test(monkeypatch, handler, **kwargs):
    async def go():
        async def allowed(host):
            pass
        monkeypatch.setattr(S, "_public_dns", allowed)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as client:
            return await S.safe_get(client, "https://clik.nanet.go.kr/openapi/minutes.do", ["clik.nanet.go.kr"], **kwargs)
    return asyncio.run(go())


def test_credentialed_redirect_never_follows(monkeypatch):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://clik.nanet.go.kr/other"})
    with pytest.raises(S.SecurityError):
        _network_test(monkeypatch, handler, credentialed=True, params={"key": "synthetic-key"})
    assert len(seen) == 1


def test_external_redirect_rejected_before_second_fetch(monkeypatch):
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.test/"})
    with pytest.raises(S.SecurityError):
        _network_test(monkeypatch, handler)
    assert len(seen) == 1


def test_safe_response_and_decompression_limit(monkeypatch):
    def normal(request):
        return httpx.Response(200, json={"ok": True})
    assert _network_test(monkeypatch, normal).json() == {"ok": True}
    def compressed(request):
        return httpx.Response(200, content=gzip.compress(b"x" * 5000), headers={"content-encoding": "gzip"})
    with pytest.raises(S.SecurityError):
        _network_test(monkeypatch, compressed, max_bytes=100)


def test_secret_redaction(monkeypatch):
    monkeypatch.setenv("CLIK_API_KEY", "synthetic/+key")
    value = S.redact_secrets("https://host/a?key=synthetic%2F%2Bkey&x=1 Authorization Bearer abcDEF.123")
    assert "synthetic" not in value and "abcDEF" not in value and "&x=1" in value
    assert "secret" not in S.safe_error(ValueError("secret"))


def test_remote_policy_fails_closed(monkeypatch):
    for key in ("UIJEONG_ALLOWED_HOSTS", "UIJEONG_ALLOWED_ORIGINS", "UIJEONG_BEARER_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("UIJEONG_BIND_HOST", "0.0.0.0")
    with pytest.raises(S.SecurityError):
        S.http_policy()
    monkeypatch.setenv("UIJEONG_ALLOWED_HOSTS", "mcp.example.test")
    monkeypatch.setenv("UIJEONG_BEARER_TOKEN", "s" * 32)
    assert S.http_policy()["origins"] == []  # No Origin allowed until explicitly configured.
    monkeypatch.setenv("UIJEONG_ALLOWED_ORIGINS", "*")
    with pytest.raises(S.SecurityError):
        S.http_policy()


def test_local_default_and_actual_sdk_settings(monkeypatch):
    for key in ("UIJEONG_BIND_HOST", "UIJEONG_ALLOWED_HOSTS", "UIJEONG_ALLOWED_ORIGINS", "UIJEONG_BEARER_TOKEN", "PORT"):
        monkeypatch.delenv(key, raising=False)
    assert S.bind_host() == "127.0.0.1"
    settings = S.transport_security_settings()
    assert settings.enable_dns_rebinding_protection is True
    assert "127.0.0.1:8000" in settings.allowed_hosts


def _guard_request(headers=None, chunks=None, *, token="s" * 32, max_body=10, calls=1):
    async def go():
        async def inner(scope, receive, send):
            assert S.REQUEST_SCOPE.get() != "local"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        policy = {"hosts": ["mcp.example.test"], "origins": ["https://app.example.test"], "token": token}
        guard = S.HTTPGuard(inner, policy, max_body=max_body, requests_per_minute=1)
        output = []
        for _ in range(calls):
            body = iter(chunks or [{"type": "http.request", "body": b"{}", "more_body": False}])
            async def receive():
                return next(body)
            async def send(event):
                output.append(event)
            await guard({"type": "http", "headers": headers or [(b"host", b"mcp.example.test"), (b"authorization", ("Bearer " + token).encode())]}, receive, send)
        assert S.REQUEST_SCOPE.get() == "local"
        return [event["status"] for event in output if event["type"] == "http.response.start"]
    return asyncio.run(go())


@pytest.mark.parametrize("extra,code", [
    ([(b"host", b"evil.test")], 403),
    ([(b"host", b"mcp.example.test"), (b"origin", b"null")], 403),
    ([(b"host", b"mcp.example.test")], 401),
    ([(b"host", b"mcp.example.test"), (b"host", b"evil.test")], 400),
])
def test_http_guard_headers(extra, code):
    assert _guard_request(extra) == [code]


def test_http_guard_chunked_size_and_rate():
    chunks = [{"type": "http.request", "body": b"123456", "more_body": True}, {"type": "http.request", "body": b"78901", "more_body": False}]
    assert _guard_request(chunks=chunks) == [413]
    assert _guard_request(calls=2) == [200, 429]


def test_schema_digest_stable():
    assert S.schema_fingerprint({"b": 2, "a": 1}) == S.schema_fingerprint({"a": 1, "b": 2})
    assert S.schema_fingerprint({"a": 1}) != S.schema_fingerprint({"a": 2})
