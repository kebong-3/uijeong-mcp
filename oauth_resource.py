"""OAuth protected-resource support using RFC 7662 token introspection.

This is NOT an authorization server: login, authorization-code + PKCE, client
registration and token issuance remain with a separately configured identity
provider. Only the administrator-configured HTTPS introspection endpoint ever
receives a token. No token is forwarded to CLIK or meeting-record websites.
"""
from __future__ import annotations
import asyncio
import collections
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit, quote


class AuthFailure(Exception):
    def __init__(self, code: str = 'invalid_token', http_status: int = 401):
        self.code, self.http_status = code, http_status
        super().__init__(code)  # Never copy identity-provider error bodies or tokens.


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    resource: str
    introspection_url: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...] = ('council:read',)
    allowed_subjects: tuple[str, ...] = ()
    cache_seconds: int = 0  # Fail closed on revocation by default: no positive cache.

    @classmethod
    def from_env(cls) -> 'OAuthConfig':
        import runtime_security as R
        def required(name):
            value=os.environ.get(name,'').strip()
            if not value:raise R.SecurityError(f'{name} 설정이 필요합니다.')
            return value
        issuer=required('UIJEONG_OAUTH_ISSUER')
        resource=required('UIJEONG_RESOURCE_URL')
        endpoint=required('UIJEONG_OAUTH_INTROSPECTION_URL')
        for value in (issuer,resource,endpoint):
            parts=urlsplit(value)
            if parts.query or parts.fragment or not parts.hostname or any(ch.isspace() or ch in '"\\' for ch in value):
                raise R.SecurityError('OAuth URL은 쿼리·프래그먼트 없는 HTTPS 주소여야 합니다.')
            R.validate_url(value,[parts.hostname])
        # Canonical endpoint is exact: audience /mcp is not silently rewritten to /.
        if urlsplit(resource).path != '/mcp':
            raise R.SecurityError('UIJEONG_RESOURCE_URL은 실제 HTTPS /mcp 주소로 지정하세요.')
        scopes=tuple(dict.fromkeys(required('UIJEONG_OAUTH_SCOPES').split()))
        if not scopes or len(scopes)>8 or any(not re.fullmatch(r'[A-Za-z0-9:_./-]{1,100}',v) for v in scopes):
            raise R.SecurityError('OAuth 범위는 공백으로 구분한 1~8개 scope입니다.')
        try:cache=int(os.environ.get('UIJEONG_OAUTH_CACHE_SECONDS','0'))
        except ValueError:raise R.SecurityError('OAuth 캐시 시간은 0~15 정수입니다.') from None
        if not 0<=cache<=15:raise R.SecurityError('OAuth 캐시 시간은 0~15 정수입니다.')
        subjects=tuple(x.strip() for x in os.environ.get('UIJEONG_OAUTH_ALLOWED_SUBJECTS','').split(',') if x.strip())
        return cls(issuer,resource,endpoint,required('UIJEONG_OAUTH_CLIENT_ID'),
                   required('UIJEONG_OAUTH_CLIENT_SECRET'),scopes,subjects,cache)

    @property
    def metadata_path(self) -> str:
        return '/.well-known/oauth-protected-resource' + urlsplit(self.resource).path

    @property
    def metadata_url(self) -> str:
        url=urlsplit(self.resource)
        return f'{url.scheme}://{url.netloc}{self.metadata_path}'

    def metadata(self) -> dict:
        return {'resource':self.resource,'authorization_servers':[self.issuer],
                'scopes_supported':list(self.scopes),'bearer_methods_supported':['header']}

    def challenge(self, error: str | None = None) -> str:
        # Values originate only from validated configuration or constants.
        value=f'Bearer resource_metadata="{self.metadata_url}", scope="{" ".join(self.scopes)}"'
        if error in ('invalid_token','insufficient_scope'):value+=f', error="{error}"'
        return value


def validate_introspection(data: Any, cfg: OAuthConfig, now: float) -> dict:
    """Stricter than RFC7662 minimum: require issuer, audience, exp, sub and scope."""
    if not isinstance(data,dict) or data.get('active') is not True:
        raise AuthFailure()
    if data.get('iss') != cfg.issuer:
        raise AuthFailure()
    aud=data.get('aud')
    audiences=[aud] if isinstance(aud,str) else aud
    if not isinstance(audiences,list) or any(not isinstance(x,str) for x in audiences) or cfg.resource not in audiences:
        raise AuthFailure()
    exp=data.get('exp')
    if isinstance(exp,bool) or not isinstance(exp,(int,float)) or not math.isfinite(exp) or exp<=now:
        raise AuthFailure()
    nbf=data.get('nbf')
    if nbf is not None and (isinstance(nbf,bool) or not isinstance(nbf,(int,float)) or not math.isfinite(nbf) or nbf>now):
        raise AuthFailure()
    if not isinstance(data.get('token_type','Bearer'),str) or data.get('token_type','Bearer').lower()!='bearer':
        raise AuthFailure()
    subject=data.get('sub')
    if not isinstance(subject,str) or not subject or len(subject)>512:
        raise AuthFailure()
    if cfg.allowed_subjects and subject not in cfg.allowed_subjects:
        raise AuthFailure('insufficient_scope',403)
    scope=data.get('scope')
    if not isinstance(scope,str) or not set(cfg.scopes)<=set(scope.split()):
        raise AuthFailure('insufficient_scope',403)
    # Stable over token rotation; neither token nor raw subject goes in storage IDs.
    principal='oauth:'+hashlib.sha256((cfg.issuer+'\0'+subject).encode()).hexdigest()
    return {'identity':principal,'expires_at':float(exp)}


class IntrospectionVerifier:
    def __init__(self,cfg:OAuthConfig,*,transport=None,clock=time.time):
        self.cfg,self.transport,self.clock=cfg,transport,clock
        self.cache: collections.OrderedDict[str,tuple[float,dict]] = collections.OrderedDict()
        self.lock=asyncio.Lock()
        self.fail_until=0.0

    async def verify(self,token:str)->dict:
        if not re.fullmatch(r'[A-Za-z0-9._~+/-]{1,8192}=*',token):raise AuthFailure()
        now=self.clock(); digest=hashlib.sha256(token.encode()).hexdigest()
        # Serialized, bounded requests prevent introspection stampedes.
        async with self.lock:
            now=self.clock()
            for key,(until,_) in list(self.cache.items()):
                if until<=now:self.cache.pop(key,None)
            hit=self.cache.get(digest)
            if hit and hit[0]>now:return dict(hit[1])
            if now<self.fail_until:raise AuthFailure('authorization_service_unavailable',503)
            try:
                import httpx
                import runtime_security as R
                host=R.validate_url(self.cfg.introspection_url,[urlsplit(self.cfg.introspection_url).hostname])
                await R._public_dns(host)
                # RFC6749 client_secret_basic uses form-encoding before Basic encoding.
                auth=httpx.BasicAuth(quote(self.cfg.client_id,safe=''),quote(self.cfg.client_secret,safe=''))
                async with httpx.AsyncClient(transport=self.transport,timeout=httpx.Timeout(8.0),
                            verify=True,trust_env=False,follow_redirects=False) as client:
                    async with client.stream('POST',self.cfg.introspection_url,auth=auth,
                         data={'token':token,'token_type_hint':'access_token'},
                         headers={'Accept':'application/json'}) as response:
                        if response.status_code!=200:
                            raise AuthFailure('authorization_service_unavailable',503)
                        raw=bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw)>65536:raise AuthFailure('authorization_service_unavailable',503)
                        data=json.loads(raw)
                result=validate_introspection(data,self.cfg,self.clock())
            except AuthFailure as exc:
                if exc.http_status==503:self.fail_until=self.clock()+2
                raise
            except (ValueError,TypeError,AttributeError,OSError,httpx.HTTPError):
                self.fail_until=self.clock()+2
                raise AuthFailure('authorization_service_unavailable',503) from None
            if self.cfg.cache_seconds:
                self.cache[digest]=(min(self.clock()+self.cfg.cache_seconds,result['expires_at']),dict(result))
                while len(self.cache)>256:self.cache.popitem(last=False)
            return result
