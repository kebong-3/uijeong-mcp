"""Prepare v3.0.1 stability release manifest; no network calls."""
from pathlib import Path
import hashlib, json, py_compile

ROOT=Path(__file__).resolve().parents[1]

def main():
    service=(ROOT/"service_v2.py").read_text(encoding="utf-8")
    assert "collect_site" not in service
    assert "await U.site" not in service
    assert "source in ('auto','site')" not in service
    assert "'direct_adapters':['CLIK']" in service
    assert 'VERSION = "3.0.1-public.1"' in (ROOT/"release_info.py").read_text(encoding="utf-8")
    assert 'VERSION = "3.0.1-public.1"' in (ROOT/"v3_reliability.py").read_text(encoding="utf-8")
    for path in ["service_v2.py","runtime_security.py","public_server.py","v3_reliability.py","release_info.py","public_site.py"]:
        py_compile.compile(str(ROOT/path),doraise=True)

    mpath=ROOT/"release_manifest.json"
    m=json.loads(mpath.read_text(encoding="utf-8"))
    runtime=[*ROOT.glob("*.py"),*ROOT.glob("data/*.json"),ROOT/"requirements.txt"]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(runtime) if p.is_file()}
    m["version"]="3.0.1-public.1"
    m["based_on"]="3.0.0-public.1"
    m["runtime_sha256"]=hashes
    m["runtime_fingerprint"]=hashlib.sha256(
        json.dumps(hashes,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    m["runtime_protocol_claim"]="V3.0.1_STABILITY; CLIK_ONLY_COUNCIL_RETRIEVAL; TRANSPORT_HEADROOM_8; TOOL_CONCURRENCY_3; PUBLIC_RPM_360"
    m["deployment_performed_in_this_build"]=False
    m.setdefault("profile_tool_counts",{}).update(public=21,full=44)
    for p in [ROOT/"tests/test_stability_v301.py",ROOT/"tests/test_public_mode.py",
              ROOT/"tests/test_v3_reliability.py",ROOT/"render.yaml",Path(__file__)]:
        if p.is_file():
            m.setdefault("files_sha256",{})[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    mpath.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"version":m["version"],"runtime_files":len(hashes),"fingerprint":m["runtime_fingerprint"]}))

if __name__=="__main__":
    main()
