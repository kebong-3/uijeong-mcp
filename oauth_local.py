"""Private single-operator OAuth authorization-code + S256 PKCE for MCP.
No anonymous tool access. All codes and tokens are hashed in private SQLite.
DCR client descriptors survive redeploys; lost token storage requires re-login.
For organization-wide SSO use the existing external OAuth resource-server mode.
"""
from __future__ import annotations
import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

SCOPE = 'council:read'
ACCESS_TTL = 3600
REFRESH_TTL = 7 * 86400
FLOW_TTL = 300
MAX_BODY = 16384
COOKIE = '__Host-uijeong_oauth'
SAFE_HEADERS = {
    'Cache-Control': 'no-store', 'Pragma': 'no-cache',
    'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
}
PUBLIC_PATHS = frozenset({
    '/', '/.well-known/oauth-authorization-server',
    '/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp',
    '/oauth/register', '/oauth/authorize', '/oauth/approve', '/oauth/token', '/oauth/revoke',
})

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')

def _unb64(value: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('invalid encoding')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password: str, salt: bytes | None = None) -> str:
    if not 24 <= len(password) <= 256:
        raise ValueError('Operator password must contain 24 to 256 characters.')
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return 'scrypt$16384$8$1$' + _b64(salt) + '$' + _b64(digest)

def verify_password(password: str, encoded: str) -> bool:
    try:
        if not 1 <= len(password) <= 256:
            return False
        algorithm, n, r, p, salt, expected = encoded.split('$')
        if (algorithm, n, r, p) != ('scrypt', '16384', '8', '1'):
            return False
        value = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(value, _unb64(expected))
    except (ValueError, TypeError):
        return False

class OAuthError(Exception):
    def __init__(self, error: str = 'invalid_request', status: int = 400):
        self.error, self.status = error, status
        super().__init__(error)

@dataclass(frozen=True)
class LocalOAuthConfig:
    issuer: str
    resource: str
    signing_key: bytes = field(repr=False)
    admin_password_hash: str = field(repr=False)
    db_path: Path
    extra_redirects: tuple[str, ...] = ()
    scopes: tuple[str, ...] = (SCOPE,)

    @classmethod
    def from_env(cls) -> 'LocalOAuthConfig':
        import runtime_security as R
        resource = os.environ.get('UIJEONG_RESOURCE_URL', '').strip()
        parts = urlsplit(resource)
        if (parts.scheme != 'https' or not parts.hostname or parts.path != '/mcp'
                or parts.query or parts.fragment or parts.username or parts.password
                or any(c.isspace() or c in '\\"' for c in resource)):
            raise R.SecurityError('UIJEONG_RESOURCE_URL에는 정확한 HTTPS /mcp 주소가 필요합니다.')
        R.validate_url(resource, [parts.hostname])
        seed = os.environ.get('UIJEONG_BEARER_TOKEN', '')
        encoded = os.environ.get('UIJEONG_OAUTH_ADMIN_PASSWORD_HASH', '')
        if len(seed) < 32:
            raise R.SecurityError('OAuth 서명키 보호를 위해 기존 UIJEONG_BEARER_TOKEN을 유지하세요.')
        try:
            a, n, r, p, salt, digest = encoded.split('$')
            valid = (a, n, r, p) == ('scrypt', '16384', '8', '1') and len(_unb64(salt)) == 16 and len(_unb64(digest)) == 32
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise R.SecurityError('유효한 UIJEONG_OAUTH_ADMIN_PASSWORD_HASH 설정이 필요합니다.')
        extra = tuple(x.strip() for x in os.environ.get('UIJEONG_OAUTH_REDIRECT_URIS', '').split(',') if x.strip())
        for value in extra:
            u = urlsplit(value)
            if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment:
                raise R.SecurityError('추가 OAuth 반환 주소는 정확한 HTTPS 주소여야 합니다.')
        issuer = urlunsplit((parts.scheme, parts.netloc, '', '', ''))
        key = hmac.new(seed.encode(), b'uijeong-local-oauth-clients-v1', hashlib.sha256).digest()
        path = Path(os.environ.get('UIJEONG_OAUTH_STATE_DB', str(R.state_path().with_name('oauth.sqlite3'))))
        return cls(issuer, resource, key, encoded, path, extra)

    @property
    def metadata_path(self) -> str:
        return '/.well-known/oauth-protected-resource/mcp'

    @property
    def metadata_url(self) -> str:
        return self.issuer + self.metadata_path

    @property
    def epoch(self) -> str:
        return hmac.new(self.signing_key, self.admin_password_hash.encode(), hashlib.sha256).hexdigest()

    def metadata(self) -> dict:
        return {'resource': self.resource, 'authorization_servers': [self.issuer],
                'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header'],
                'resource_name': '지방의회 MCP'}

    def challenge(self, error: str | None = None) -> str:
        value = f'Bearer resource_metadata="{self.metadata_url}", scope="{SCOPE}"'
        if error in ('invalid_token', 'insufficient_scope'):
            value += f', error="{error}"'
        return value

    def allowed_redirect(self, uri: str) -> bool:
        if not isinstance(uri, str) or len(uri) > 2048 or any(c.isspace() or c in '\\"' for c in uri):
            return False
        u = urlsplit(uri)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment:
            return False
        if uri in self.extra_redirects:
            return True
        return (u.netloc == 'chatgpt.com' and not u.query and
                (u.path == '/connector_platform_oauth_redirect' or
                 re.fullmatch(r'/connector/oauth/[A-Za-z0-9_-]{1,200}', u.path) is not None))

class LocalOAuthServer:
    def __init__(self, cfg: LocalOAuthConfig, *, clock=time.time):
        self.cfg, self.clock = cfg, clock
        import runtime_security as R
        with R._connect(cfg.db_path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS oauth_items (digest TEXT PRIMARY KEY, kind TEXT NOT NULL, family TEXT NOT NULL, expires REAL NOT NULL, active INTEGER NOT NULL, value TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS oauth_expiry ON oauth_items(expires)')
            db.execute('CREATE INDEX IF NOT EXISTS oauth_family ON oauth_items(family)')
            db.execute('CREATE TABLE IF NOT EXISTS oauth_limits (bucket TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL)')

    def _connect(self):
        import runtime_security as R
        return R._connect(self.cfg.db_path)

    def _limit(self, bucket: str, limit: int) -> None:
        window = int(self.clock() // 60)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO oauth_limits VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET window=excluded.window, count=CASE WHEN oauth_limits.window=excluded.window THEN oauth_limits.count+1 ELSE 1 END', (bucket, window))
            count = db.execute('SELECT count FROM oauth_limits WHERE bucket=?', (bucket,)).fetchone()[0]
            db.execute('COMMIT')
        if count > limit:
            raise OAuthError('temporarily_unavailable', 429)

    def _store(self, db, token: str, kind: str, value: dict, ttl: int, family: str = '') -> None:
        db.execute('DELETE FROM oauth_items WHERE expires<=?', (self.clock(),))
        if db.execute('SELECT COUNT(*) FROM oauth_items').fetchone()[0] >= 4000:
            raise OAuthError('temporarily_unavailable', 503)
        db.execute('INSERT INTO oauth_items VALUES(?,?,?,?,1,?)',
                   (_hash(token), kind, family, self.clock() + ttl, json.dumps(value, separators=(',', ':'))))

    def _load(self, db, token: str, kind: str, *, active: bool = True):
        if not isinstance(token, str) or not 20 <= len(token) <= 8192:
            return None
        row = db.execute('SELECT family,expires,active,value FROM oauth_items WHERE digest=? AND kind=?', (_hash(token), kind)).fetchone()
        if not row or row[1] <= self.clock() or (active and row[2] != 1):
            return None
        return {'family': row[0], 'expires': row[1], 'active': row[2], 'data': json.loads(row[3])}

    def _client_id(self, data: dict) -> str:
        payload = _b64(json.dumps(data, separators=(',', ':'), ensure_ascii=True).encode())
        sig = _b64(hmac.new(self.cfg.signing_key, payload.encode(), hashlib.sha256).digest())
        return 'uijc1.' + payload + '.' + sig

    def _client(self, client_id: str) -> dict:
        try:
            if not isinstance(client_id, str) or len(client_id) > 12000:
                raise ValueError()
            prefix, payload, sig = client_id.split('.')
            expected = hmac.new(self.cfg.signing_key, payload.encode(), hashlib.sha256).digest()
            if prefix != 'uijc1' or not hmac.compare_digest(_unb64(sig), expected):
                raise ValueError()
            data = json.loads(_unb64(payload))
            if not data['redirect_uris'] or not all(self.cfg.allowed_redirect(v) for v in data['redirect_uris']):
                raise ValueError()
            return data
        except (ValueError, KeyError, TypeError):
            raise OAuthError('invalid_client', 401) from None

    def _client_secret(self, client_id: str) -> str:
        return _b64(hmac.new(self.cfg.signing_key, ('client-secret\0' + client_id).encode(), hashlib.sha256).digest())

    def _authenticate_client(self, data: dict[str, str], request: Request) -> tuple[str, dict]:
        client_id = data.get('client_id', '')
        supplied = data.get('client_secret', '')
        used_method = 'client_secret_post' if 'client_secret' in data else 'none'
        header = request.headers.get('authorization')
        if header:
            if not header.startswith('Basic ') or supplied:
                raise OAuthError('invalid_client', 401)
            try:
                from urllib.parse import unquote_plus
                raw = base64.b64decode(header[6:], validate=True).decode()
                cid, supplied = (unquote_plus(x) for x in raw.split(':', 1))
            except (ValueError, UnicodeError):
                raise OAuthError('invalid_client', 401) from None
            if client_id and client_id != cid:
                raise OAuthError('invalid_client', 401)
            client_id = cid
            used_method = 'client_secret_basic'
        client = self._client(client_id)
        if client['token_endpoint_auth_method'] != used_method:
            raise OAuthError('invalid_client', 401)
        if used_method != 'none' and not hmac.compare_digest(supplied.encode(), self._client_secret(client_id).encode()):
            raise OAuthError('invalid_client', 401)
        return client_id, client

    @staticmethod
    def _pairs(pairs) -> dict:
        data = {}
        for key, value in pairs:
            if key in data:
                raise OAuthError()
            data[key] = value
        return data

    async def _body(self, request: Request, *, json_body: bool = False) -> dict:
        ctype = request.headers.get('content-type', '').split(';')[0].strip().lower()
        if ctype != ('application/json' if json_body else 'application/x-www-form-urlencoded'):
            raise OAuthError('invalid_request', 415)
        async def collect():
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > MAX_BODY:
                    raise OAuthError('invalid_request', 413)
            return bytes(raw)
        try:
            raw = await asyncio.wait_for(collect(), 10)
            if json_body:
                data = json.loads(raw, object_pairs_hook=self._pairs)
            else:
                data = self._pairs(parse_qsl(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=40))
            if not isinstance(data, dict):
                raise OAuthError()
            return data
        except (ValueError, UnicodeError, asyncio.TimeoutError):
            raise OAuthError() from None

    def _json(self, data: dict, status: int = 200) -> Response:
        return JSONResponse(data, status_code=status, headers=SAFE_HEADERS)

    def _authorization_metadata(self) -> dict:
        return {'issuer': self.cfg.issuer,
                'authorization_endpoint': self.cfg.issuer + '/oauth/authorize',
                'token_endpoint': self.cfg.issuer + '/oauth/token',
                'registration_endpoint': self.cfg.issuer + '/oauth/register',
                'revocation_endpoint': self.cfg.issuer + '/oauth/revoke',
                'response_types_supported': ['code'],
                'grant_types_supported': ['authorization_code', 'refresh_token'],
                'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic'],
                'code_challenge_methods_supported': ['S256'],
                'scopes_supported': [SCOPE],
                'authorization_response_iss_parameter_supported': True}

    async def register(self, request: Request) -> Response:
        self._limit('registration', 20)
        data = await self._body(request, json_body=True)
        redirects = data.get('redirect_uris')
        method = data.get('token_endpoint_auth_method', 'none')
        if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 4 or
                not all(self.cfg.allowed_redirect(v) for v in redirects)):
            raise OAuthError('invalid_redirect_uri')
        if method not in ('none', 'client_secret_post', 'client_secret_basic'):
            raise OAuthError('invalid_client_metadata')
        if data.get('scope', SCOPE) != SCOPE:
            raise OAuthError('invalid_scope')
        if data.get('response_types', ['code']) != ['code']:
            raise OAuthError('invalid_client_metadata')
        grants = data.get('grant_types', ['authorization_code', 'refresh_token'])
        if not isinstance(grants, list) or 'authorization_code' not in grants or any(v not in ('authorization_code', 'refresh_token') for v in grants):
            raise OAuthError('invalid_client_metadata')
        name = data.get('client_name', 'ChatGPT')
        if not isinstance(name, str) or len(name) > 100:
            raise OAuthError('invalid_client_metadata')
        descriptor = {'redirect_uris': redirects, 'token_endpoint_auth_method': method,
                      'client_name': name, 'nonce': secrets.token_urlsafe(18)}
        client_id = self._client_id(descriptor)
        output = dict(descriptor, client_id=client_id, client_id_issued_at=int(self.clock()),
                      grant_types=grants, response_types=['code'], scope=SCOPE)
        output.pop('nonce')
        if method != 'none':
            output.update(client_secret=self._client_secret(client_id), client_secret_expires_at=0)
        return self._json(output, 201)

    async def authorize(self, request: Request) -> Response:
        self._limit('authorize', 30)
        if len(request.scope.get('query_string', b'')) > MAX_BODY:
            raise OAuthError()
        data = self._pairs(request.query_params.multi_items())
        client = self._client(data.get('client_id', ''))
        uri = data.get('redirect_uri', '')
        if uri not in client['redirect_uris']:
            raise OAuthError('invalid_redirect_uri')
        if (data.get('response_type') != 'code' or data.get('code_challenge_method') != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', data.get('code_challenge', ''))):
            raise OAuthError()
        if data.get('resource') != self.cfg.resource:
            raise OAuthError('invalid_target')
        if data.get('scope', SCOPE).split() != [SCOPE]:
            raise OAuthError('invalid_scope')
        if len(data.get('state', '')) > 2048:
            raise OAuthError()
        flow, csrf, cookie = (secrets.token_urlsafe(32) for _ in range(3))
        stored = {k: data.get(k, '') for k in ('client_id', 'redirect_uri', 'state', 'code_challenge', 'resource')}
        stored.update(scope=SCOPE, csrf=_hash(csrf), cookie=_hash(cookie), epoch=self.cfg.epoch)
        with self._connect() as db:
            self._store(db, flow, 'flow', stored, FLOW_TTL)
        esc = html.escape
        page = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>지방의회 MCP 연결 승인</title>
<style>body{{font-family:system-ui,sans-serif;background:#f3f5f8;color:#172b46;margin:0;padding:32px 16px}}main{{max-width:520px;margin:5vh auto;background:white;padding:32px;border-radius:18px}}h1{{font-size:25px}}p{{line-height:1.7}}label{{display:block;margin-top:22px}}input[type=password]{{box-sizing:border-box;width:100%;font-size:18px;padding:12px;margin:8px 0 18px}}button{{font-size:16px;padding:12px 18px;border:0;border-radius:8px;cursor:pointer}}button[value=approve]{{background:#174e8c;color:white}}small{{display:block;margin-top:20px;line-height:1.6;overflow-wrap:anywhere}}</style>
<main><h1>지방의회 MCP 연결 승인</h1><p><b>{esc(client['client_name'])}</b>의 연결을 승인합니다.<br>권한: 의회 공개자료 조회 및 답변 준비 도구 이용.</p>
<form method="post" action="/oauth/approve"><input type="hidden" name="flow" value="{flow}"><input type="hidden" name="csrf" value="{csrf}">
<label for="password">관리자 연결 비밀번호</label><input id="password" type="password" name="password" autocomplete="current-password" maxlength="256" required>
<button name="decision" value="approve">로그인하고 연결 승인</button> <button name="decision" value="deny" formnovalidate>취소</button></form>
<small>CLIK API 키나 ChatGPT 비밀번호를 입력하지 마세요.<br>이 서버 전용 관리자 연결 비밀번호만 사용합니다.<br>돌아갈 주소: {esc(uri)}</small></main></html>'''
        response = HTMLResponse(page, headers=SAFE_HEADERS)
        response.set_cookie(COOKIE, cookie, max_age=FLOW_TTL, secure=True, httponly=True, samesite='lax', path='/')
        return response

    def _redirect(self, stored: dict, **params) -> Response:
        uri = stored['redirect_uri']
        values = dict(params, iss=self.cfg.issuer)
        if stored.get('state'):
            values['state'] = stored['state']
        response = RedirectResponse(uri + ('&' if '?' in uri else '?') + urlencode(values), status_code=303, headers=SAFE_HEADERS)
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='lax')
        return response

    async def approve(self, request: Request) -> Response:
        self._limit('approval', 12)
        if request.headers.get('origin') != self.cfg.issuer:
            raise OAuthError('access_denied', 403)
        data = await self._body(request)
        with self._connect() as db:
            row = self._load(db, data.get('flow', ''), 'flow')
        if (not row or row['data']['epoch'] != self.cfg.epoch or
                not hmac.compare_digest(row['data']['csrf'], _hash(data.get('csrf', ''))) or
                not hmac.compare_digest(row['data']['cookie'], _hash(request.cookies.get(COOKIE, '')))):
            raise OAuthError('access_denied', 403)
        stored = row['data']
        if data.get('decision') not in ('approve', 'deny'):
            raise OAuthError()
        if data['decision'] == 'approve':
            valid = await asyncio.to_thread(verify_password, data.get('password', ''), self.cfg.admin_password_hash)
            if not valid:
                return HTMLResponse('<html lang="ko"><meta charset="utf-8"><p>연결 비밀번호가 맞지 않습니다. 뒤로 돌아가 다시 입력하세요.</p></html>', status_code=401, headers=SAFE_HEADERS)
        code = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE oauth_items SET active=0 WHERE digest=? AND active=1 AND expires>?', (_hash(data['flow']), self.clock())).rowcount
            if not changed:
                raise OAuthError('access_denied', 403)
            if data['decision'] == 'approve':
                self._store(db, code, 'code', {k: v for k, v in stored.items() if k not in ('csrf', 'cookie')}, 60)
            db.execute('COMMIT')
        return self._redirect(stored, **({'code': code} if data['decision'] == 'approve' else {'error': 'access_denied'}))

    def _issue(self, db, stored: dict, family: str) -> dict:
        access, refresh = 'uija_' + secrets.token_urlsafe(32), 'uijr_' + secrets.token_urlsafe(32)
        value = {k: stored[k] for k in ('client_id', 'scope', 'resource', 'epoch')}
        value.update(issuer=self.cfg.issuer, subject='operator')
        self._store(db, access, 'access', value, ACCESS_TTL, family)
        self._store(db, refresh, 'refresh', value, REFRESH_TTL, family)
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': ACCESS_TTL,
                'refresh_token': refresh, 'scope': SCOPE}

    async def token(self, request: Request) -> Response:
        self._limit('token', 60)
        data = await self._body(request)
        client_id, client = self._authenticate_client(data, request)
        if data.get('resource') != self.cfg.resource:
            raise OAuthError('invalid_target')
        grant = data.get('grant_type')
        if grant not in ('authorization_code', 'refresh_token'):
            raise OAuthError('unsupported_grant_type')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if grant == 'authorization_code':
                raw = data.get('code', '')
                row = self._load(db, raw, 'code')
                if not row:
                    raise OAuthError('invalid_grant')
                stored = row['data']
                verifier = data.get('code_verifier', '')
                if (stored['client_id'] != client_id or stored['redirect_uri'] != data.get('redirect_uri') or
                        stored['epoch'] != self.cfg.epoch or stored['resource'] != data['resource'] or
                        not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or
                        not hmac.compare_digest(stored['code_challenge'], _b64(hashlib.sha256(verifier.encode()).digest()))):
                    raise OAuthError('invalid_grant')
                db.execute('UPDATE oauth_items SET active=0 WHERE digest=?', (_hash(raw),))
                output = self._issue(db, stored, secrets.token_urlsafe(24))
            else:
                raw = data.get('refresh_token', '')
                row = self._load(db, raw, 'refresh', active=False)
                if not row or row['data']['client_id'] != client_id or row['data']['epoch'] != self.cfg.epoch:
                    raise OAuthError('invalid_grant')
                if not row['active']:
                    db.execute('UPDATE oauth_items SET active=0 WHERE family=?', (row['family'],))
                    db.execute('COMMIT')
                    raise OAuthError('invalid_grant')
                if data.get('scope', SCOPE) != SCOPE:
                    raise OAuthError('invalid_scope')
                db.execute('UPDATE oauth_items SET active=0 WHERE digest=?', (_hash(raw),))
                output = self._issue(db, row['data'], row['family'])
            db.execute('COMMIT')
        return self._json(output)

    async def revoke(self, request: Request) -> Response:
        self._limit('token', 60)
        data = await self._body(request)
        client_id, _ = self._authenticate_client(data, request)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for kind in ('access', 'refresh'):
                row = self._load(db, data.get('token', ''), kind, active=False)
                if row and row['data']['client_id'] == client_id:
                    db.execute('UPDATE oauth_items SET active=0 WHERE family=?', (row['family'],))
            db.execute('COMMIT')
        return self._json({})

    async def verify(self, token: str) -> dict:
        from oauth_resource import AuthFailure
        if not re.fullmatch(r'uija_[A-Za-z0-9_-]{43}', token):
            raise AuthFailure()
        with self._connect() as db:
            row = self._load(db, token, 'access')
        if not row:
            raise AuthFailure()
        value = row['data']
        if (value.get('epoch') != self.cfg.epoch or value.get('resource') != self.cfg.resource
                or value.get('issuer') != self.cfg.issuer or value.get('scope') != SCOPE
                or value.get('subject') != 'operator'):
            raise AuthFailure()
        return {'identity': 'oauth:' + _hash(self.cfg.issuer + '\0operator'), 'expires_at': row['expires']}

    async def handle(self, scope, receive, send) -> None:
        request = Request(scope, receive)
        path, method = request.url.path, request.method
        try:
            self._limit('all_oauth', 240)
            if path in ('/.well-known/oauth-protected-resource', self.cfg.metadata_path) and method in ('GET', 'HEAD'):
                response = self._json(self.cfg.metadata())
            elif path == '/.well-known/oauth-authorization-server' and method in ('GET', 'HEAD'):
                response = self._json(self._authorization_metadata())
            elif path == '/' and method in ('GET', 'HEAD'):
                from release_info import VERSION
                response = HTMLResponse(f'<html lang="ko"><meta charset="utf-8"><title>지방의회 MCP</title><h1>지방의회 MCP</h1><p>서버가 실행 중입니다. 버전: {html.escape(VERSION)}</p><p>ChatGPT 연결 주소: {html.escape(self.cfg.resource)}</p><p>인증 방식은 OAuth입니다. ChatGPT에서 연결을 시작하고 관리자 연결 비밀번호로 승인하세요.</p></html>', headers=SAFE_HEADERS)
            else:
                routes = {('/oauth/register', 'POST'): self.register,
                          ('/oauth/authorize', 'GET'): self.authorize,
                          ('/oauth/approve', 'POST'): self.approve,
                          ('/oauth/token', 'POST'): self.token,
                          ('/oauth/revoke', 'POST'): self.revoke}
                handler = routes.get((path, method))
                if handler is None:
                    raise OAuthError('invalid_request', 405)
                response = await handler(request)
        except OAuthError as exc:
            response = self._json({'error': exc.error}, exc.status)
            if exc.status in (429, 503):
                response.headers['Retry-After'] = '60'
        if method == 'HEAD':
            response.body = b''
            response.headers['content-length'] = '0'
        await response(scope, receive, send)
