"""Bounded network access, local persistence and HTTP guards for 의정소통 MCP.

Static bearer authentication is for a trusted single-organization deployment. It
is not an OAuth authorization server or per-user authorization implementation.
SQLite coordinates processes sharing one local file, not different server nodes.
"""
from __future__ import annotations

import asyncio
import collections
import contextvars
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import time
from typing import Any, Callable, Iterable
from urllib.parse import quote, urljoin, urlsplit

KST = dt.timezone(dt.timedelta(hours=9))
REQUEST_SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("uijeong_scope", default="local")
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
PUBLIC_KINDS = frozenset({"CLIK", "PUBLIC_CLIK", "PUBLIC_COUNCIL", "COUNCIL_SITE", "OFFICIAL_MINUTES", "OFFICIAL_FETCHED", "PUBLIC_WEB"})


class SecurityError(ValueError):
    """Unsafe configuration, destination or payload; message contains no secrets."""


def key_scope(api_key: str, namespace: str = "clik") -> str:
    """Use a non-reversible identifier for counters, never the actual key."""
    return namespace + ":" + hashlib.sha256((namespace + "\0" + api_key).encode()).hexdigest()


def schema_fingerprint(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def redact_secrets(value: Any, extra_secrets: Iterable[str] = ()) -> str:
    text = str(value)
    known = [os.environ.get("CLIK_API_KEY", ""), os.environ.get("UIJEONG_BEARER_TOKEN", ""), *extra_secrets]
    for secret in sorted((s for s in known if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]").replace(quote(secret, safe=""), "[REDACTED]")
    text = re.sub(r"(?i)([?&](?:key|api_?key|servicekey|access_token|token)=)[^&\s\"'<>]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    return text


def safe_error(exc: BaseException) -> str:
    """Network exception strings may include query credentials; omit them."""
    return f"요청 실패({type(exc).__name__}). 인증정보와 서버 응답 원문은 표시하지 않습니다."


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        # Traceback exception text may carry a URL; transport logs need only type.
        if record.exc_info:
            record.msg += " [" + record.exc_info[0].__name__ + "]"
            record.exc_info = None
            record.exc_text = None
        return True


def configure_logging() -> None:
    for name in ("httpx", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access"):
        log = logging.getLogger(name)
        log.addFilter(SecretFilter())
    # HTTPX logs complete query strings at INFO. Credentialed requests use this.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def state_path() -> Path:
    explicit = os.environ.get("UIJEONG_STATE_DB", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    base = Path(os.environ.get("UIJEONG_DATA_DIR", str(Path.home() / ".local" / "share" / "uijeong-mcp"))).expanduser()
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return base / "state.sqlite3"


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args: Any) -> None:
        try:
            super().__exit__(*args)
        finally:
            self.close()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, factory=_ClosingConnection)
    os.chmod(path, 0o600)
    conn.execute("PRAGMA busy_timeout=15000")
    # DELETE avoids WAL sidecars and keeps all durable state in one private file.
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


class SQLiteBudget:
    """Atomic KST-day reservation. Failed upstream attempts still consume budget."""
    def __init__(self, path: str | Path | None = None, daily_limit: int = 1000,
                 scope: str = "clik", *, clock: Callable[[], float] = time.time):
        if isinstance(daily_limit, bool) or not isinstance(daily_limit, int) or daily_limit < 1:
            raise ValueError("daily_limit must be a positive integer")
        self.path, self.daily_limit, self.scope, self.clock = Path(path) if path else state_path(), daily_limit, scope, clock
        with _connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS api_budget (scope TEXT NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL CHECK(calls>=0), PRIMARY KEY(scope,day))")

    def _day(self) -> str:
        return dt.datetime.fromtimestamp(self.clock(), KST).date().isoformat()

    def reserve(self, cost: int = 1) -> bool:
        if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
            raise ValueError("cost must be a positive integer")
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            day = self._day()
            conn.execute("INSERT OR IGNORE INTO api_budget VALUES(?,?,0)", (self.scope, day))
            changed = conn.execute("UPDATE api_budget SET calls=calls+? WHERE scope=? AND day=? AND calls+?<=?",
                                   (cost, self.scope, day, cost, self.daily_limit)).rowcount
            conn.execute("COMMIT")
            return bool(changed)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        day = self._day()
        with _connect(self.path) as conn:
            row = conn.execute("SELECT calls FROM api_budget WHERE scope=? AND day=?", (self.scope, day)).fetchone()
        used = int(row[0]) if row else 0
        return {"day_kst": day, "attempted_calls": used, "configured_limit": self.daily_limit,
                "remaining_estimate": max(0, self.daily_limit - used),
                "accounting_scope": "같은 SQLite 파일을 공유하는 프로세스·재시작",
                "official_remaining": False,
                "limitation": "다른 서버·다른 프로그램에서 같은 인증키로 호출한 횟수는 포함하지 않음"}

    def remaining(self) -> int:
        return self.status()["remaining_estimate"]


class SnapshotStore:
    """Opaque IDs, scope isolation, TTL, payload limits, bounded row count.

    TTL prevents reads after expiry and removes expired records on access/write;
    it is not cryptographic erasure from backups. The caller must label origins
    from actual retrieval, never from untrusted text's self-declared provenance.
    """
    def __init__(self, path: str | Path | None = None, scope: str = "local", *,
                 allow_private: bool = False, max_bytes: int = 4 * 1024 * 1024,
                 max_entries: int = 500, clock: Callable[[], float] = time.time,
                 evict_oldest: bool = False, max_total_bytes: int = 0):
        """``evict_oldest`` is opt-in and must be reported by the caller.

        Refusing to store is the safe default: evicting an unexpired snapshot
        invalidates a cursor someone may still be paging. A shared deployment
        needs the opposite trade-off — one stalled cursor beats a store that
        stops accepting new evidence for everyone until TTL — so it enables
        eviction explicitly and surfaces ``evicted`` in the tool response.
        """
        if not scope or max_bytes < 1 or max_entries < 1 or max_total_bytes < 0:
            raise ValueError("Invalid snapshot storage limits")
        self.path, self.scope = Path(path) if path else state_path(), scope
        self.allow_private, self.max_bytes, self.max_entries, self.clock = allow_private, max_bytes, max_entries, clock
        self.evict_oldest, self.max_total_bytes = evict_oldest, max_total_bytes
        self.evicted = 0
        with _connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, scope TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS snapshot_expiry ON snapshots(expires)")

    def put(self, payload: Any, ttl_seconds: int = 86400, source_kind: str = "PUBLIC_CLIK") -> str:
        if source_kind not in PUBLIC_KINDS and not self.allow_private:
            raise SecurityError("사용자 제공·합성 원문 저장은 명시적으로 허용된 로컬 보관함에서만 가능합니다.")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 7 * 86400:
            raise ValueError("Snapshot TTL must be between one second and seven days")
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(raw.encode()) > self.max_bytes:
            raise SecurityError("증거 묶음이 보관 한도를 초과했습니다. 검색 범위를 줄여주세요.")
        ident, now = secrets.token_hex(32), self.clock()
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM snapshots WHERE expires<=?", (now,))
            count = conn.execute("SELECT count(*) FROM snapshots WHERE scope=?", (self.scope,)).fetchone()[0]
            if count >= self.max_entries and self.evict_oldest:
                surplus = count - self.max_entries + 1
                removed = conn.execute(
                    "DELETE FROM snapshots WHERE id IN (SELECT id FROM snapshots WHERE scope=?"
                    " ORDER BY created ASC LIMIT ?)", (self.scope, surplus)).rowcount
                self.evicted += removed
                count -= removed
            if count >= self.max_entries:
                # Never invalidate an unexpired cursor silently by eviction.
                raise SecurityError("증거 보관 한도에 도달했습니다. 기존 묶음 만료 후 재시도하세요.")
            if self.max_total_bytes:
                total = conn.execute("SELECT coalesce(sum(length(payload)),0) FROM snapshots WHERE scope=?",
                                     (self.scope,)).fetchone()[0]
                while total + len(raw) > self.max_total_bytes and self.evict_oldest:
                    row = conn.execute("SELECT id,length(payload) FROM snapshots WHERE scope=?"
                                       " ORDER BY created ASC LIMIT 1", (self.scope,)).fetchone()
                    if not row:
                        break
                    conn.execute("DELETE FROM snapshots WHERE id=?", (row[0],))
                    self.evicted += 1
                    total -= row[1]
                if total + len(raw) > self.max_total_bytes:
                    raise SecurityError("증거 보관 용량 한도를 초과했습니다. 검색 범위를 줄여주세요.")
            conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?)", (ident, self.scope, now, now + ttl_seconds, source_kind, raw))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return ident

    def get(self, ident: str) -> Any | None:
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{64}", ident):
            return None
        with _connect(self.path) as conn:
            conn.execute("DELETE FROM snapshots WHERE expires<=?", (self.clock(),))
            row = conn.execute("SELECT payload FROM snapshots WHERE id=? AND scope=? AND expires>?", (ident, self.scope, self.clock())).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, ident: str) -> bool:
        with _connect(self.path) as conn:
            return bool(conn.execute("DELETE FROM snapshots WHERE id=? AND scope=?", (ident, self.scope)).rowcount)


def validate_url(url: str, allowed_hosts: Iterable[str]) -> str:
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url) or "\\" in url:
        raise SecurityError("허용되지 않은 원문 주소입니다.")
    try:
        p = urlsplit(url)
        host = (p.hostname or "").encode("idna").decode("ascii").lower()
        allowed = {h.encode("idna").decode("ascii").lower() for h in allowed_hosts}
        if p.scheme != "https" or host not in allowed or p.username or p.password or p.port not in (None, 443) or p.fragment:
            raise SecurityError("HTTPS 공식 허용 도메인의 주소만 조회할 수 있습니다.")
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, SecurityError):
            raise
        raise SecurityError("원문 주소 형식이 올바르지 않습니다.") from None
    try:
        if not ipaddress.ip_address(host).is_global:
            raise SecurityError("내부 네트워크 주소는 조회할 수 없습니다.")
    except ValueError as exc:
        if isinstance(exc, SecurityError):
            raise
    return host


async def _public_dns(host: str) -> None:
    try:
        records = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(r[4][0]) for r in records]
    except (OSError, ValueError):
        raise SecurityError("공식 도메인의 주소를 확인하지 못했습니다.") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise SecurityError("내부 네트워크로 연결되는 도메인은 조회할 수 없습니다.")


async def safe_get(client: Any, url: str, allowed_hosts: Iterable[str], *, params: dict | None = None,
                   max_bytes: int = MAX_RESPONSE_BYTES, max_redirects: int = 2,
                   credentialed: bool = False) -> Any:
    """Read a bounded decoded body; never forward query credentials on redirect.

    DNS is preflight checked, not socket-pinned; the exact administrator-owned
    official-domain allowlist remains the trust boundary. Do not allow arbitrary
    user hosts. The client must use TLS validation and trust_env=False.
    """
    if max_bytes < 1 or max_redirects < 0:
        raise ValueError("Invalid network limits")
    import httpx
    hosts = tuple(allowed_hosts)
    for hop in range(max_redirects + 1):
        host = validate_url(url, hosts)
        await _public_dns(host)
        async with client.stream("GET", url, params=params if hop == 0 else None, follow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                if credentialed or hop >= max_redirects:
                    raise SecurityError("인증정보 보호 또는 이동 횟수 제한으로 리디렉션을 중단했습니다.")
                location = response.headers.get("location")
                if not location:
                    raise SecurityError("리디렉션에 목적지 주소가 없습니다.")
                url = urljoin(str(response.url), location)
                validate_url(url, hosts)
                continue
            response.raise_for_status()
            try:
                if int(response.headers.get("content-length", "0")) > max_bytes:
                    raise SecurityError("원문 응답이 허용 크기를 초과했습니다.")
            except ValueError as exc:
                if isinstance(exc, SecurityError):
                    raise
                raise SecurityError("원문 응답 크기 정보가 올바르지 않습니다.") from None
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise SecurityError("원문 응답이 허용 크기를 초과했습니다.")
                chunks.append(chunk)
            headers = dict(response.headers)
            # The returned bytes are already decompressed; avoid double decoding.
            headers.pop("content-encoding", None)
            headers.pop("content-length", None)
            return httpx.Response(response.status_code, headers=headers, content=b"".join(chunks), request=response.request)
    raise SecurityError("원문 이동 횟수를 초과했습니다.")


def _csv_env(name: str) -> list[str]:
    return [value.strip().lower() for value in os.environ.get(name, "").split(",") if value.strip()]


def http_policy() -> dict[str, Any]:
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise SecurityError("PORT는 1~65535여야 합니다.")
    host = os.environ.get("UIJEONG_BIND_HOST", "127.0.0.1").strip()
    remote = host not in ("127.0.0.1", "localhost", "::1")
    token = os.environ.get("UIJEONG_BEARER_TOKEN", "")
    hosts = _csv_env("UIJEONG_ALLOWED_HOSTS")
    origins = _csv_env("UIJEONG_ALLOWED_ORIGINS")
    if remote and (not hosts or len(token) < 32):
        raise SecurityError("외부 HTTP 공개에는 UIJEONG_ALLOWED_HOSTS와 32자 이상 UIJEONG_BEARER_TOKEN이 필요합니다.")
    if any("*" in value or "/" in value or "@" in value for value in hosts):
        raise SecurityError("허용 Host에는 정확한 도메인 또는 도메인:포트만 입력하세요.")
    if not hosts:
        hosts = [f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"]
    if not origins and not remote:
        origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"]
    if any("*" in value or value == "null" for value in origins):
        raise SecurityError("허용 Origin에 와일드카드·null을 사용할 수 없습니다.")
    for origin in origins:
        parts = urlsplit(origin)
        if parts.scheme not in (("https",) if remote else ("http", "https")) or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username or parts.password:
            raise SecurityError("허용 Origin은 경로 없는 정확한 HTTPS 출처여야 합니다.")
    return {"host": host, "port": port, "remote": remote, "token": token, "hosts": hosts, "origins": origins}


def bind_host() -> str:
    return http_policy()["host"]


def transport_security_settings() -> Any:
    from mcp.server.transport_security import TransportSecuritySettings
    policy = http_policy()
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=policy["hosts"], allowed_origins=policy["origins"])


class HTTPGuard:
    """Pure ASGI wrapper; bounded body, exact headers, bearer and rate limit.

    Limits are per process. The single bearer maps to one organization scope;
    trusted proxy headers are deliberately ignored. Multi-user OAuth requires a
    separate authenticated gateway with its own authorization and rate policy.
    """
    def __init__(self, app: Any, policy: dict[str, Any] | None = None, *,
                 max_body: int = 1024 * 1024, requests_per_minute: int = 120):
        self.app, self.policy = app, policy if policy is not None else http_policy()
        self.max_body, self.requests_per_minute = max_body, requests_per_minute
        self.requests: dict[str, collections.deque[float]] = {}

    async def _reject(self, send: Any, code: int, message: str) -> None:
        payload = json.dumps({"error": message}, ensure_ascii=False).encode()
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if code == 401:
            headers.append((b"www-authenticate", b'Bearer realm="uijeong-mcp"'))
        await send({"type": "http.response.start", "status": code, "headers": headers})
        await send({"type": "http.response.body", "body": payload})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.decode("latin1").lower(), []).append(value.decode("latin1"))
        if any(len(headers.get(name, [])) > 1 for name in ("host", "origin", "authorization", "content-length")):
            await self._reject(send, 400, "중복 보안 헤더")
            return
        host = headers.get("host", [""])[0].lower()
        if host not in self.policy["hosts"]:
            await self._reject(send, 403, "허용되지 않은 Host")
            return
        origin = headers.get("origin", [None])[0]
        if origin is not None and origin.lower() not in self.policy["origins"]:
            await self._reject(send, 403, "허용되지 않은 Origin")
            return
        token = self.policy["token"]
        auth = headers.get("authorization", [""])[0]
        if token and not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
            await self._reject(send, 401, "인증 필요")
            return
        identity = key_scope(token, "http") if token else "local"
        now = time.monotonic()
        queue = self.requests.setdefault(identity, collections.deque())
        while queue and queue[0] <= now - 60:
            queue.popleft()
        if len(queue) >= self.requests_per_minute:
            await self._reject(send, 429, "분당 요청 한도 초과")
            return
        queue.append(now)
        try:
            declared = int(headers.get("content-length", ["0"])[0])
        except ValueError:
            await self._reject(send, 400, "잘못된 요청 크기")
            return
        if declared < 0 or declared > self.max_body:
            await self._reject(send, 413, "요청 크기 한도 초과")
            return
        events, total, body_started = [], 0, time.monotonic()
        while True:
            try:
                event = await asyncio.wait_for(receive(), timeout=max(0, 30 - (time.monotonic() - body_started)))
            except asyncio.TimeoutError:
                await self._reject(send, 408, "요청 본문 수신 시간 초과")
                return
            if event["type"] == "http.disconnect":
                return
            total += len(event.get("body", b""))
            if total > self.max_body or len(events) >= 4096:
                await self._reject(send, 413, "요청 크기 한도 초과")
                return
            events.append(event)
            if not event.get("more_body", False):
                break
        index = 0
        async def replay() -> Any:
            nonlocal index
            if index < len(events):
                item = events[index]
                index += 1
                return item
            return await receive()
        context_token = REQUEST_SCOPE.set(identity)
        try:
            await self.app(scope, replay, send)
        finally:
            REQUEST_SCOPE.reset(context_token)


def secure_http_app(app: Any) -> HTTPGuard:
    return HTTPGuard(app)
