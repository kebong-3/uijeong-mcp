"""Bounded network access, local persistence and HTTP guards for 의정소통 MCP.

Static bearer is a legacy single-organization path. OAuth mode verifies tokens
with a separately administered authorization server; it does not issue tokens.
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
from urllib.parse import quote, urljoin, urlsplit, parse_qsl

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
    known = [os.environ.get("CLIK_API_KEY", ""), os.environ.get("UIJEONG_BEARER_TOKEN", ""),
             os.environ.get("UIJEONG_OAUTH_CLIENT_SECRET", ""),
             os.environ.get("UIJEONG_VERIFY_TOKEN", ""), *extra_secrets]
    for secret in sorted((s for s in known if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]").replace(quote(secret, safe=""), "[REDACTED]")
    # Only an exact, public council record URL may retain its document key.
    # Do not globally exempt `key`: CLIK's API uses that name for credentials.
    public_keys = {}
    def protect_public_url(match):
        raw = match.group(0)
        try:
            parsed = urlsplit(raw)
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            if (parsed.scheme == 'https' and parsed.hostname in ('www.gjsc.or.kr', 'gjsc.or.kr')
                    and not parsed.username and not parsed.password and parsed.port in (None, 443)
                    and parsed.path in ('/record/recordView.do', '/record/originalDownload.do')
                    and len(pairs) == 1 and pairs[0][0] == 'key'
                    and re.fullmatch(r'[A-Za-z0-9]{1,128}', pairs[0][1])):
                marker = '__PUBLIC_RECORD_' + secrets.token_hex(16) + '__'
                public_keys[marker] = raw
                return marker
        except ValueError:
            pass
        return raw
    text = re.sub(r'https://[^\s\"\'<>\[\]()]+', protect_public_url, text)
    text = re.sub(r"(?i)([?&](?:key|api_?key|authkey|servicekey|access_token|token|signature|x-amz-signature)=)[^&\s\"'<>]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    for marker, url in public_keys.items():
        text = text.replace(marker, url)
    return text


def safe_error(exc: BaseException) -> str:
    """Network exception strings may include query credentials; omit them."""
    return f"요청 실패({type(exc).__name__}). 인증정보와 서버 응답 원문은 표시하지 않습니다."


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's AccessFormatter unpacks these five arguments. Preserve
        # their shape and numeric status code while redacting string fields.
        if (record.name == "uvicorn.access" and isinstance(record.args, tuple)
                and len(record.args) == 5):
            record.msg = redact_secrets(record.msg)
            record.args = tuple(redact_secrets(value) if isinstance(value, str)
                                else value for value in record.args)
        else:
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
                 evict_oldest: bool = False, max_total_bytes: int = 0, bind_request_scope: bool = False):
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
        self.bind_request_scope = bind_request_scope
        with _connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, scope TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS snapshot_expiry ON snapshots(expires)")

    def effective_scope(self) -> str:
        identity = REQUEST_SCOPE.get()
        return self.scope if not self.bind_request_scope or identity == 'local' else self.scope + ':' + identity

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
            quota_where, quota_args = ('', ()) if self.bind_request_scope else (' WHERE scope=?', (self.effective_scope(),))
            count = conn.execute("SELECT count(*) FROM snapshots" + quota_where, quota_args).fetchone()[0]
            if count >= self.max_entries and self.evict_oldest:
                surplus = count - self.max_entries + 1
                removed = conn.execute(
                    "DELETE FROM snapshots WHERE id IN (SELECT id FROM snapshots" + quota_where +
                    " ORDER BY created ASC LIMIT ?)", (*quota_args, surplus)).rowcount
                self.evicted += removed
                count -= removed
            if count >= self.max_entries:
                # Never invalidate an unexpired cursor silently by eviction.
                raise SecurityError("증거 보관 한도에 도달했습니다. 기존 묶음 만료 후 재시도하세요.")
            if self.max_total_bytes:
                total = conn.execute("SELECT coalesce(sum(length(CAST(payload AS BLOB))),0) FROM snapshots" + quota_where,
                                     quota_args).fetchone()[0]
                while total + len(raw.encode()) > self.max_total_bytes and self.evict_oldest:
                    row = conn.execute("SELECT id,length(CAST(payload AS BLOB)) FROM snapshots" + quota_where +
                                       " ORDER BY created ASC LIMIT 1", quota_args).fetchone()
                    if not row:
                        break
                    conn.execute("DELETE FROM snapshots WHERE id=?", (row[0],))
                    self.evicted += 1
                    total -= row[1]
                if total + len(raw.encode()) > self.max_total_bytes:
                    raise SecurityError("증거 보관 용량 한도를 초과했습니다. 검색 범위를 줄여주세요.")
            conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?)", (ident, self.effective_scope(), now, now + ttl_seconds, source_kind, raw))
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
            row = conn.execute("SELECT payload FROM snapshots WHERE id=? AND scope=? AND expires>?", (ident, self.effective_scope(), self.clock())).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, ident: str) -> bool:
        with _connect(self.path) as conn:
            return bool(conn.execute("DELETE FROM snapshots WHERE id=? AND scope=?", (ident, self.effective_scope())).rowcount)


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
    if is_public_mode():
        return public_http_policy()
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise SecurityError("PORT는 1~65535여야 합니다.")
    host = os.environ.get("UIJEONG_BIND_HOST", "127.0.0.1").strip()
    remote = host not in ("127.0.0.1", "localhost", "::1")
    token = os.environ.get("UIJEONG_BEARER_TOKEN", "")
    hosts = _csv_env("UIJEONG_ALLOWED_HOSTS")
    origins = _csv_env("UIJEONG_ALLOWED_ORIGINS")
    mode = os.environ.get('UIJEONG_AUTH_MODE', 'auto').strip().lower()
    if mode == 'auto':mode = 'bearer' if token else 'local'
    if mode not in ('bearer','oauth','local'):
        raise SecurityError('UIJEONG_AUTH_MODE는 bearer|oauth|local|auto입니다.')
    if remote and mode == 'local':
        raise SecurityError('외부 HTTP에는 인증이 필요합니다. local 모드는 루프백 전용입니다.')
    if mode == 'bearer' and len(token)<32:
        raise SecurityError('Bearer 모드에는 32자 이상 UIJEONG_BEARER_TOKEN이 필요합니다.')
    oauth = None
    if mode == 'oauth':
        from oauth_resource import OAuthConfig
        oauth = OAuthConfig.from_env()
        if token:
            raise SecurityError('OAuth 모드에서는 UIJEONG_BEARER_TOKEN을 제거하세요. 두 인증을 혼용하지 않습니다.')
        if urlsplit(oauth.resource).netloc.lower() not in hosts:
            raise SecurityError('UIJEONG_RESOURCE_URL 호스트를 UIJEONG_ALLOWED_HOSTS에 정확히 지정하세요.')
    if remote and (not hosts or (mode == 'bearer' and len(token) < 32)):
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
    return {"host": host, "port": port, "remote": remote, "token": token, "hosts": hosts, "origins": origins, "auth_mode": mode, "oauth": oauth}


def auth_diagnostics() -> dict:
    """Report configuration stages only. No secret values or live-login claims."""
    if is_public_mode():
        return public_auth_diagnostics()
    try: policy=http_policy()
    except SecurityError as exc:
        return {'status':'CONFIG_INVALID','code':'AUTH_CONFIG_ERROR','message':str(exc),'remote_login_tested':False}
    mode=policy['auth_mode']
    return {'status':'CONFIG_VALID','mode':mode,'remote_login_tested':False,
            'clik_api_is_separate_credential':True,
            'connection_requirement': ('별도 인증서버의 authorization-code + PKCE 설정 및 실제 로그인 시험 필요' if mode=='oauth' else
                 '정적 Bearer를 전달할 수 있는 클라이언트/게이트웨이 전용; ChatGPT 직접 OAuth 인증과 다름' if mode=='bearer' else
                 '127.0.0.1 등 루프백 로컬 실행 전용'),
            'oauth_token_check': 'RFC7662 introspection' if mode=='oauth' else None}


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
    trusted proxy headers are deliberately ignored. OAuth uses an external authorization server and per-subject request scopes.
    Limits are process-local; multiple replicas need an upstream shared rate policy.
    """
    def __init__(self, app: Any, policy: dict[str, Any] | None = None, *,
                 max_body: int = 1024 * 1024, requests_per_minute: int = 120):
        self.app, self.policy = app, policy if policy is not None else http_policy()
        if self.policy.get("auth_mode") == "public":
            if not getattr(app, "uijeong_public_readonly", False):
                raise SecurityError("공개 인증은 public_server의 허용목록 전용 앱에서만 사용할 수 있습니다.")
            self.app = PublicBoundary(app, max_concurrent=3)
            max_body = min(max_body, 65536)
            requests_per_minute = min(requests_per_minute, 120)
        self.max_body, self.requests_per_minute = max_body, requests_per_minute
        self.requests: dict[str, collections.deque[float]] = {}
        self.oauth_verifier = None
        if self.policy.get('auth_mode') == 'oauth':
            from oauth_resource import IntrospectionVerifier
            self.oauth_verifier=IntrospectionVerifier(self.policy['oauth'])
        self.pre_auth_requests: collections.deque[float] = collections.deque()

    async def _reject(self, send: Any, code: int, message: str) -> None:
        payload = json.dumps({"error": message}, ensure_ascii=False).encode()
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if code in (401,403) and self.policy.get('oauth'):
            challenge=self.policy['oauth'].challenge('insufficient_scope' if code==403 else 'invalid_token')
            headers.append((b"www-authenticate", challenge.encode()))
        elif code == 401:
            headers.append((b"www-authenticate", b'Bearer realm="uijeong-mcp"'))
        if code in (429,503):headers.append((b'retry-after', b'2' if code==503 else b'60'))
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
        from release_info import VERSION
        path=scope.get('path','/mcp')
        method=scope.get('method','POST')
        public_metadata = self.policy.get('oauth') and path in (
            '/.well-known/oauth-protected-resource', self.policy['oauth'].metadata_path)
        if (path=='/healthz' or public_metadata) and method in ('GET','HEAD'):
            payload = self.policy['oauth'].metadata() if public_metadata else {'status':'ok','version':VERSION}
            encoded=json.dumps(payload,ensure_ascii=False).encode()
            await send({'type':'http.response.start','status':200,'headers':[
                (b'content-type',b'application/json'),(b'cache-control',b'no-store'),
                (b'x-content-type-options',b'nosniff')]})
            await send({'type':'http.response.body','body':b'' if method=='HEAD' else encoded})
            return
        token = self.policy.get("token",'')
        auth = headers.get("authorization", [""])[0]
        if self.oauth_verifier is not None:
            # Shared pre-auth budget avoids unbounded remote introspection work.
            stamp=time.monotonic()
            while self.pre_auth_requests and self.pre_auth_requests[0]<=stamp-60:self.pre_auth_requests.popleft()
            if len(self.pre_auth_requests)>=240:
                await self._reject(send,429,'인증 확인 요청 한도 초과');return
            self.pre_auth_requests.append(stamp)
            if not auth.lower().startswith('bearer '):
                await self._reject(send,401,'OAuth 인증 필요');return
            from oauth_resource import AuthFailure
            try:identity=(await self.oauth_verifier.verify(auth[7:]))['identity']
            except AuthFailure as exc:
                await self._reject(send,exc.http_status,exc.code);return
        else:
            if token and not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
                await self._reject(send,401,'MCP Bearer 인증 필요; CLIK_API_KEY와 다른 인증입니다.');return
            identity = key_scope(token,"http") if token else "local"
        now = time.monotonic()
        for existing,q in list(self.requests.items()):
            if not q or q[-1]<=now-60:self.requests.pop(existing,None)
        if identity not in self.requests and len(self.requests)>=1000:
            await self._reject(send,429,'동시 인증 주체 한도 초과');return
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


# Explicit anonymous mode: the protected modes above retain their behavior.
def is_public_mode() -> bool:
    return os.environ.get("UIJEONG_AUTH_MODE", "auto").strip().lower() in ("public", "none")


def public_http_policy() -> dict[str, Any]:
    if os.environ.get("UIJEONG_PUBLIC_READONLY", "").lower() != "true":
        raise SecurityError("공개 모드는 UIJEONG_PUBLIC_READONLY=true를 명시해야 합니다.")
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise SecurityError("PORT는 1~65535여야 합니다.")
    host = os.environ.get("UIJEONG_BIND_HOST", "127.0.0.1").strip()
    remote = host not in ("127.0.0.1", "localhost", "::1")
    hosts = _csv_env("UIJEONG_ALLOWED_HOSTS")
    origins = _csv_env("UIJEONG_ALLOWED_ORIGINS")
    if remote and not hosts:
        raise SecurityError("공개 HTTP에는 UIJEONG_ALLOWED_HOSTS의 정확한 도메인이 필요합니다.")
    if any(not h or any(c in h for c in "*/@?#\\") or any(c.isspace() for c in h) for h in hosts):
        raise SecurityError("허용 Host에는 정확한 도메인 또는 도메인:포트만 입력하세요.")
    if not hosts:
        hosts = [f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"]
    if not origins and not remote:
        origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}", f"http://[::1]:{port}"]
    for origin in origins:
        parts = urlsplit(origin)
        if ("*" in origin or parts.scheme not in (("https",) if remote else ("http", "https"))
                or not parts.netloc or parts.path or parts.query or parts.fragment
                or parts.username or parts.password):
            raise SecurityError("허용 Origin은 경로 없는 정확한 출처여야 합니다.")
    # A retained legacy secret is not an alternative authentication path.
    return {"host": host, "port": port, "remote": remote, "hosts": hosts,
            "origins": origins, "auth_mode": "public", "token": "", "oauth": None}


def public_auth_diagnostics() -> dict[str, Any]:
    try:
        http_policy()
    except (ValueError, SecurityError) as exc:
        return {"status": "CONFIG_INVALID", "code": "PUBLIC_CONFIG_ERROR",
                "message": safe_error(exc), "remote_login_tested": False}
    return {"status": "CONFIG_VALID", "mode": "public", "authentication": "none",
            "public_readonly": True, "remote_login_tested": False,
            "clik_api_is_separate_credential": True,
            "connection_requirement": "인증 없음. 공개 회의록 조회 도구만 제공하며 내부자료를 입력하지 마세요.",
            "limits_scope": "single-process shared public budget; not a per-user quota"}


async def _public_reply(send: Any, status: int, payload: dict[str, Any]) -> None:
    headers = [(b"content-type", b"application/json; charset=utf-8"),
               (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
    if status == 503:
        headers.append((b"retry-after", b"2"))
    if status == 405:
        headers.append((b"allow", b"POST"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": json.dumps(payload, ensure_ascii=False).encode()})


class PublicBoundary:
    """Bounded burst queue, global concurrency cap and public snapshot namespace."""
    def __init__(self, app: Any, max_concurrent: int = 3, *, max_waiting: int = 12,
                 queue_timeout: float = 20.0):
        self.app, self.max_concurrent, self.active = app, max_concurrent, 0
        self.max_waiting, self.queue_timeout, self.waiting = max_waiting, queue_timeout, 0
        self._slots = asyncio.Semaphore(max_concurrent)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path", "").rstrip("/") != "/mcp":
            await _public_reply(send, 404, {"error": "Not found"})
            return
        if scope.get("method") != "POST":
            await _public_reply(send, 405, {"authentication": "none", "public_readonly": True,
                "message": "MCP 프로그램에서 POST로 연결하세요. 서버 상태 확인 주소는 /healthz입니다."})
            return
        if self.waiting >= self.max_waiting and self._slots.locked():
            await _public_reply(send, 503, {"error": "PUBLIC_BUSY", "message": "동시 조회 중입니다. 잠시 후 다시 시도하세요."})
            return
        self.waiting += 1
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=self.queue_timeout)
        except asyncio.TimeoutError:
            await _public_reply(send, 503, {"error": "PUBLIC_QUEUE_TIMEOUT", "message": "조회 대기시간을 초과했습니다. 잠시 후 다시 시도하세요."})
            return
        finally:
            self.waiting -= 1
        self.active += 1
        context_token = REQUEST_SCOPE.set("public-readonly-v1")
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST_SCOPE.reset(context_token)
            self.active -= 1
            self._slots.release()
