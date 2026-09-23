"""Single release version and reproducible, secret-free deployment attestation."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

VERSION = "2.5.3-public.1"
CAPABILITIES = ["one_call_response_preparation", "exact_source_claim_audit",
                "dimension_checked_metric_comparison", "side_by_side_evidence_comparison",
                "date_bounded_department_aliases", "recurring_topic_cues_not_verdicts",
                "preserve_partial_empty_distinction", "rolling_and_explicit_periods",
                "oauth_introspection_resource_server", "request_scoped_snapshots",
                "utf8_storage_budget", "deployment_manifest_verification",
                "explicit_public_readonly_profile", "public_concurrency_limit",
                "clickable_verified_citations", "bounded_public_burst_queue",
                "acting_chair_speaker_boundaries",
                "employee_public_workflows", "workspace_distribution_ready"]


def runtime_files(root: Path) -> list[Path]:
    paths = [*root.glob('*.py'), *root.glob('data/*.json')]
    paths += [root / 'requirements.txt']
    return sorted((p for p in paths if p.is_file()), key=lambda p: p.relative_to(root).as_posix())


def module_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime_files(root)}


def runtime_fingerprint(root: Path) -> str:
    raw=json.dumps(module_hashes(root),sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_manifest(root: Path) -> dict:
    path=root/'release_manifest.json'
    if not path.exists():return {'status':'UNAVAILABLE','note':'manifest 파일이 없습니다.'}
    try:
        manifest=json.loads(path.read_text())
        expected=manifest.get('runtime_sha256')
        if not isinstance(expected,dict):return {'status':'UNSUPPORTED_MANIFEST'}
        actual=module_hashes(root)
        different=sorted(k for k in set(actual)|set(expected) if actual.get(k)!=expected.get(k))
        match=not different and manifest.get('version')==VERSION
        return {'status':'MATCH' if match else 'MISMATCH', 'expected_version':manifest.get('version'),
                'different_paths':different,'file_count':len(actual),
                'note':'파일 내용 일치 확인이며 제작자 서명·실제 클라이언트 인증 성공을 증명하지 않습니다.'}
    except (OSError,ValueError,TypeError):return {'status':'INVALID_MANIFEST'}
