#!/usr/bin/env python3
"""Secret-free preflight. Public mode also tests the installed SDK in process."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_security as R
import release_info as V


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http', action='store_true', help='HTTP bind/host/auth policy 검사')
    parser.add_argument('--manifest', action='store_true', help='로컬 코드 해시 검사')
    args = parser.parse_args()
    report = {'version': V.VERSION, 'network_called': False, 'login_verified': False,
              'auth': R.auth_diagnostics()}
    ok = True
    if args.http:
        try:
            policy = R.http_policy()
            report['http'] = {'status': 'VALID_CONFIGURATION_ONLY', 'bind_host': policy['host'],
                              'allowed_hosts': policy['hosts'], 'auth_mode': policy['auth_mode']}
        except (ValueError, R.SecurityError) as exc:
            report['http'] = {'status': 'INVALID_CONFIGURATION', 'message': R.safe_error(exc)}
            ok = False
    if args.manifest:
        report['manifest'] = V.verify_manifest(Path(__file__).resolve().parents[1])
        ok = ok and report['manifest']['status'] == 'MATCH'
    if ok and args.http and R.is_public_mode():
        try:
            from public_server import self_test
            report['public_protocol'] = asyncio.run(self_test())
        except Exception as exc:
            report['public_protocol'] = {'status': 'FAIL', 'error_type': type(exc).__name__,
                                         'message': R.safe_error(exc)}
            ok = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
