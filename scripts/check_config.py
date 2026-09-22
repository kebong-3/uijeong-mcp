#!/usr/bin/env python3
"""Secret-free preflight; no SDK, API requests, dotenv loading, or login attempt."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runtime_security as R
import release_info as V

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http',action='store_true',help='HTTP bind/host/auth policy 검사')
    parser.add_argument('--manifest',action='store_true',help='로컬 코드 해시 검사; 불일치 시 종료코드 1')
    args=parser.parse_args()
    report={'version':V.VERSION,'network_called':False,'login_verified':False,
            'auth':R.auth_diagnostics()}
    ok=True
    if args.http:
        try:
            policy=R.http_policy()
            report['http']={'status':'VALID_CONFIGURATION_ONLY','bind_host':policy['host'],
                'allowed_hosts':policy['hosts'],'auth_mode':policy['auth_mode']}
        except (ValueError,R.SecurityError) as exc:
            report['http']={'status':'INVALID_CONFIGURATION','message':R.safe_error(exc)};ok=False
    if args.manifest:
        report['manifest']=V.verify_manifest(Path(__file__).resolve().parents[1])
        ok=ok and report['manifest']['status']=='MATCH'
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
