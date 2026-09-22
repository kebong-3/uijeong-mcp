#!/usr/bin/env python3
"""Auditable one-time repair. Refuses unrecognized original runtime content.
Run on repair branch only; --check validates without modifying files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def apply():
    manifest = json.loads((ROOT/'release_manifest.json').read_text())
    runtime = ROOT/'runtime_security.py'
    text = runtime.read_text()
    if 'self.oauth_server = None' not in text:
        actual = hashlib.sha256(runtime.read_bytes()).hexdigest()
        if actual != '23c280c9e29389f32dd8bb05b3be06741dd7a363a87a4b90fcb0dad76936e474':
            raise RuntimeError('Original runtime changed. Review before applying repair.')
        def change(old, new):
            nonlocal text
            if text.count(old) != 1:
                raise RuntimeError('Repair anchor mismatch: '+old[:80])
            text = text.replace(old, new)
        change('             os.environ.get("UIJEONG_VERIFY_TOKEN", ""), *extra_secrets]', '             os.environ.get("UIJEONG_VERIFY_TOKEN", ""),\n             os.environ.get("UIJEONG_OAUTH_ADMIN_PASSWORD_HASH", ""), *extra_secrets]')
        change('(?:key|api_?key|servicekey|access_token|token)=', '(?:key|api_?key|servicekey|access_token|refresh_token|token|code|code_verifier|client_secret|password|csrf)=')
        change('    return text\n\n\ndef safe_error', '    text = re.sub(r"\\buij[ar]_[A-Za-z0-9_-]{43}\\b", "[REDACTED]", text)\n    return text\n\n\ndef safe_error')
        change('        record.msg = redact_secrets(record.getMessage())\n        record.args = ()', '''        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            # AccessFormatter requires (client, method, path, version, status).
            record.msg = redact_secrets(record.msg)
            record.args = tuple(redact_secrets(v) if isinstance(v, str) else v for v in record.args)
        else:
            record.msg = redact_secrets(record.getMessage())
            record.args = ()''')
        change("    if mode not in ('bearer','oauth','local'):", "    if mode not in ('bearer','oauth','oauth_local','local'):")
        change('UIJEONG_AUTH_MODE는 bearer|oauth|local|auto입니다.', 'UIJEONG_AUTH_MODE는 bearer|oauth|oauth_local|local|auto입니다.')
        change("    if remote and (not hosts or (mode == 'bearer' and len(token) < 32)):", '''    if mode == 'oauth_local':
        from oauth_local import LocalOAuthConfig
        oauth = LocalOAuthConfig.from_env()
        if urlsplit(oauth.resource).netloc.lower() not in hosts:
            raise SecurityError('UIJEONG_RESOURCE_URL 호스트를 UIJEONG_ALLOWED_HOSTS에 정확히 지정하세요.')
        # Existing secret becomes a domain-separated signing seed, NOT a bearer.
        token = ''
        if oauth.issuer.lower() not in origins:
            origins.append(oauth.issuer.lower())
    if remote and (not hosts or (mode == 'bearer' and len(token) < 32)):''')
        change("            'connection_requirement': ('별도 인증서버", "            'connection_requirement': ('이 서버의 관리자 로그인·명시적 승인 후 OAuth S256 PKCE 연결; 실제 ChatGPT 승인은 별도' if mode=='oauth_local' else\n                 '별도 인증서버")
        change("            'oauth_token_check': 'RFC7662 introspection' if mode=='oauth' else None}", "            'oauth_token_check': 'local opaque token store' if mode=='oauth_local' else 'RFC7662 introspection' if mode=='oauth' else None}")
        change('        self.oauth_verifier = None\n        if self.policy', '        self.oauth_verifier = None\n        self.oauth_server = None\n        if self.policy')
        change('        self.pre_auth_requests: collections.deque[float] = collections.deque()', '''        if self.policy.get('auth_mode') == 'oauth_local':
            from oauth_local import LocalOAuthServer
            self.oauth_server = LocalOAuthServer(self.policy['oauth'])
            self.oauth_verifier = self.oauth_server
        self.pre_auth_requests: collections.deque[float] = collections.deque()''')
        change("        public_metadata = self.policy.get('oauth') and path in (", '''        if self.oauth_server is not None:
            from oauth_local import PUBLIC_PATHS
            if path in PUBLIC_PATHS:
                await self.oauth_server.handle(scope, receive, send)
                return
        public_metadata = self.policy.get('oauth') and path in (''')
        runtime.write_text(text)
    inventory_path = ROOT/'docs/connection-repair-file-inventory.json'
    inventory = json.loads(inventory_path.read_text()) if inventory_path.exists() else []
    allowed = set(manifest['runtime_sha256']) | {'oauth_local.py'}
    for path in sorted(ROOT.glob('*.py')):
        if path.name in allowed:
            continue
        copies = [ROOT/d/path.name for d in ('scripts','tests') if (ROOT/d/path.name).exists() and (ROOT/d/path.name).read_bytes() == path.read_bytes()]
        if copies:
            target, action = copies[0], 'delete_identical_copy'
        else:
            target = ROOT/'docs/history/upload-recovery-20260922'/path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            action = 'archive_distinct_copy'
        inventory.append({'duplicate':path.name,'preserved_at':target.relative_to(ROOT).as_posix(),'action':action})
        path.unlink()
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    version_path = ROOT/'release_info.py'
    version_path.write_text(version_path.read_text().replace('VERSION = "2.5.0-rc.1"','VERSION = "2.5.0-rc.2"'))
    (ROOT/'pytest.ini').write_text('[pytest]\ntestpaths = tests\n')
    (ROOT/'.gitignore').write_text('.env\n.env.*\n!.env.example\n__pycache__/\n*.py[cod]\n.venv/\nvenv/\n.pytest_cache/\nstate/\n*.sqlite3*\n')
    env = (ROOT/'env.example').read_text()
    env = env.replace('work = 14 tools','work = 18 tools').replace('lite = 22 tools, full = 34 tools','lite = 26 tools, full = 38 tools')
    env += '\n# Private single-operator ChatGPT OAuth. Use env settings, never real secrets here.\n# UIJEONG_AUTH_MODE=oauth_local\n# UIJEONG_RESOURCE_URL=https://your-service.onrender.com/mcp\n# UIJEONG_OAUTH_ADMIN_PASSWORD_HASH=scrypt-format-hash-generated-outside-source\n'
    (ROOT/'.env.example').write_text(env)
    blueprint = ROOT/'render.yaml'
    s = blueprint.read_text()
    s = s.replace('# work = 14 tools for practical preparation; core = 5, lite = 22, full = 34.', '# work = 18 tools; core = 5, lite = 26, full = 38.')
    s = s.replace('      - key: UIJEONG_AUTH_MODE\n        value: bearer', '''      - key: UIJEONG_AUTH_MODE
        value: oauth_local
      - key: UIJEONG_RESOURCE_URL
        value: https://uijeong-mcp.onrender.com/mcp
      - key: UIJEONG_OAUTH_ADMIN_PASSWORD_HASH
        sync: false''')
    s = s.replace('# Compatibility template: static Bearer only. It is not direct ChatGPT OAuth.\n# See render.oauth.yaml for resource-server settings; external AS required.', '# Private single-operator OAuth login; anonymous MCP requests remain denied.\n# Existing UIJEONG_BEARER_TOKEN is used ONLY as a signing seed in oauth_local.\n# For organization-wide SSO use render.oauth.yaml and a reviewed external provider.')
    blueprint.write_text(s)
    doc = ROOT/'docs/CONNECTION_REPAIR_20260922_KO.md'
    doc.write_text('''# 지방의회 MCP 연결 복구 (2026-09-22)

버전: 2.5.0-rc.2. 기존 도구 기능은 유지합니다.

## 변경 사항
- 최상위에 잘못 올라간 Python 파일 24개 정리. 동일본 21개는 정상 폴더에 보존, 다른 내용 3개는 docs/history/upload-recovery-20260922에 이동.
- Uvicorn 로그의 필수 5개 인자를 보존하면서 인증키·토큰·인가코드를 마스킹.
- 관리자 로그인·명시적 연결 승인·S256 PKCE를 사용하는 단일 관리자 OAuth 모드 추가.
- 무인증 도구 접근은 계속 거절. CLIK API 키는 변경하지 않음.
- 배포 파일 무결성 검사를 유지하고 수정 내용에 맞게 명세 갱신.

## 운영 설정
UIJEONG_AUTH_MODE=oauth_local
UIJEONG_RESOURCE_URL=https://uijeong-mcp.onrender.com/mcp
UIJEONG_OAUTH_ADMIN_PASSWORD_HASH에는 scrypt 해시를 설정합니다. 평문 비밀번호는 저장소에 넣지 않습니다.
기존 UIJEONG_BEARER_TOKEN은 서명키를 도출하는 용도로만 보존되며, 이 모드에서 고정 Bearer 직접 로그인은 거절합니다.

## 보안 및 범위
단일 관리자 비공개 시범 운영용입니다. 기관 전체 사용자는 기존 외부 OAuth 모드와 기관의 검증된 계정/SSO를 연결하고 보안 검토를 받아야 합니다.
인가코드 60초·1회 사용, 접근 토큰 1시간, 갱신 토큰 7일·회전·재사용 시 토큰 묶음 폐기. 비밀번호·토큰 평문을 SQLite에 저장하지 않습니다.
승인 화면은 비밀번호·보안 쿠키·CSRF·동일 출처를 검증합니다. 허용된 ChatGPT 반환 주소만 사용합니다.
기관 보안 승인이나 실제 ChatGPT 사용자 승인 완료를 이 코드만으로 보장하지 않습니다.
무료 인스턴스의 비영구 저장장치와 절전 정책은 변경하지 않았고 유료 자원을 만들지 않습니다. 재배포로 토큰 DB가 사라지면 재로그인이 필요합니다.

## 연결
ChatGPT에서 기존 /mcp 주소를 OAuth 방식으로 재연결합니다. 승인 화면에는 이 서버의 관리자 연결 비밀번호를 입력합니다. CLIK API 키나 ChatGPT 계정 비밀번호가 아닙니다.

## 검증
tests/test_connection_repair.py는 합성 정보로 인증·로그 회귀시험을 수행합니다.
GitHub Actions에서 실제 라이브러리를 설치하고 전체 pytest, stdio, Streamable HTTP를 검사합니다. 결과는 해당 워크플로와 아티팩트를 확인하세요.
''')
    subprocess.run([sys.executable, str(ROOT/'scripts/build_manifest.py')], cwd=ROOT, check=True)


def check():
    import release_info as V
    report = V.verify_manifest(ROOT)
    assert V.VERSION == '2.5.0-rc.2'
    assert report['status'] == 'MATCH', report
    assert not (ROOT/'check_config.py').exists()
    assert (ROOT/'scripts/check_config.py').exists()
    print(json.dumps({'version':V.VERSION, 'manifest':report, 'network_called':False},ensure_ascii=False,indent=2))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.apply:
        apply()
    if args.check or not args.apply:
        check()
