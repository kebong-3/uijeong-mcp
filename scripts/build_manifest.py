#!/usr/bin/env python3
"""Rebuild local integrity manifest. Not a digital signature or deployment claim.
Run AFTER changing source/tests/docs, then commit the entire result together.
"""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import release_info as V
from source_contracts import build

def eligible(path):
    rel=path.relative_to(ROOT)
    return (path.is_file() and not path.is_symlink() and not any(x in rel.parts for x in
       ('state','__pycache__','.pytest_cache','.git','.venv','venv')) and
       not path.name.endswith(('.pyc','.sqlite3','.sqlite3-wal','.sqlite3-shm','.zip')) and
       path.name!='.env' and rel.as_posix()!='release_manifest.json')

def main():
    contract=build()
    (ROOT/'docs/source-tool-contracts.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
    files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(ROOT.rglob('*')) if eligible(p)}
    result={'version':V.VERSION,'based_on':'user-provided 2.4.0-rc.1','release_stage':'RELEASE_CANDIDATE',
        'runtime_sha256':V.module_hashes(ROOT),'runtime_fingerprint':V.runtime_fingerprint(ROOT),
        'profile_tool_counts':{k:len(v) for k,v in contract['profiles'].items()},
        'files_sha256':files,'integrity_note':'내용 일치 검사이며 제작자 서명·원격 배포 증명은 아닙니다.',
        'verification_reference':'docs/verification/seongnam-20261007/summary.json',
        'runtime_protocol_claim':'SEE_VERIFICATION_SUMMARY',
        'deployment_performed_in_this_build':False}
    (ROOT/'release_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'version':V.VERSION,'manifest_files':len(files),
        'runtime_files':len(result['runtime_sha256']),'local_match':V.verify_manifest(ROOT)['status']},indent=2))
if __name__=='__main__':main()
