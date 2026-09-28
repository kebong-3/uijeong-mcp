"""Apply the reviewed v3 integration to the pinned v2.9 baseline; fail closed."""
from pathlib import Path
import hashlib
import json
import py_compile

ROOT = Path(__file__).resolve().parents[1]
BASE = {
    'uijeong_mcp.py':'a07c6b1217ff1a731ba7d96311fa1bd8b5c7295a2819222d35406f49c1c55994',
    'public_server.py':'bd03242840c488b372e3465d1ca9bd7cdd9884c2984a0c2469016a9c04554867',
    'council_extensions.py':'f243eb35465fb581d1fbf8bb4208d61aa273870ce324cb6477dcd39cfd3f2529',
    'release_info.py':'ae90c0b88cfa45a03b46cd9f014f74f0bfc987636e2c7cc93f38fb2e7c79f5f1',
}


def change(path, old, new):
    p=ROOT/path
    text=p.read_text(encoding='utf-8')
    if new in text and old not in text:
        return
    if text.count(old)!=1:
        raise RuntimeError(f'Patch target must occur exactly once: {path}: {old[:70]}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')


def apply():
    installed='import v3_reliability as V' in (ROOT/'public_server.py').read_text()
    if not installed:
        for path,expected in BASE.items():
            if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected:
                raise RuntimeError(f'Baseline changed; review instead of overwriting: {path}')
        change('public_server.py','import openai_compat as O','import openai_compat as O\nimport v3_reliability as V')
        change('public_server.py','result = await asyncio.wait_for(fn(*args, **kwargs), timeout=TOOL_TIMEOUT_SECONDS)',
               'result = await asyncio.wait_for(V.run_public(fn, args, kwargs), timeout=TOOL_TIMEOUT_SECONDS)')
        change('public_server.py','연결 점검은 council_status(live=False), 실제 출처 조회 점검은 live=True입니다.',
               '연결 점검은 council_status(live=False), 실제 출처 조회 점검은 live=True입니다.\n도구 결과의 mcp_receipt는 실제 서버 반환 기록이며 출처의 정확성 보증은 아닙니다.\n후보 자료 발견을 법적 적용·동일 예산사업 확정으로 바꾸지 마세요.\nreport_mentions의 집행부 업무보고를 의원 질문으로 표현하지 마세요.\n키 설정됨과 인증·실제 데이터 반환 성공을 구분하세요.')
        change('uijeong_mcp.py','install_council_v29(sys.modules[__name__])',
               'install_council_v29(sys.modules[__name__])\nfrom v3_reliability import install as install_v3_reliability\ninstall_v3_reliability(sys.modules[__name__])')
        change('council_extensions.py','result=await F.context(topic,cname,fiscal_year,limit,search_terms=_expansions(topic,2))',
               'result=await F.context(topic,cname,fiscal_year,limit)')
        change('council_extensions.py','context = await council_context_pack(', 'context = await U.council_context_pack(')
        old='''        prepared=await U.council_prepare_pack(
            keyword=topic,council=council,date_from=date_from,date_to=date_to,
            max_docs=max_docs,snapshot_id=reuse_snapshot,max_evidence=10,
        )'''
        new='''        prepared={"status":"SKIPPED","message":"같은 조건의 근거 스냅샷 미확보. 중복 재검색 대신 확보한 출처와 미확인 사항을 반환합니다."}
        if reuse_snapshot:
            from v3_reliability import stage
            prepared=await stage(U.council_prepare_pack(
                keyword=topic,council=council,date_from=date_from,date_to=date_to,
                max_docs=max_docs,snapshot_id=reuse_snapshot,max_evidence=10,
            ), 8)'''
        change('council_extensions.py',old,new)
        change('release_info.py','VERSION = "2.9.0-public.1"','VERSION = "3.0.0-public.1"')
        change('release_info.py','"mcp_first_trace", "council_context_pack"]',
               '"mcp_first_trace", "council_context_pack",\n                "bounded_identical_request_coalescing", "live_mcp_receipt",\n                "strict_jurisdiction_candidates", "schema_errors_not_empty",\n                "partial_layer_preservation", "missing_expenditure_not_zero"]')
        change('council_v29.py','status = _coverage_status(errors=errors, returned=len(cases), requested=case_count)',
               'status = _coverage_status(errors=errors, returned=len(cases), requested=case_count)\n    limited = details_checked >= max_details or any(x["upstream_total"] > x["rows_received"] for x in list_calls)\n    if limited and len(cases) < case_count and status == "EMPTY":\n        status = "PARTIAL"')
        change('council_v29.py','"max_details": max_details,','"max_details": max_details,\n            "limited": limited,')
    change('v3_reliability.py',
           '    session.__signature__ = inspect.signature(old_session)\n    session.__annotations__ = inspect.get_annotations(old_session,eval_str=True)',
           '    ann = inspect.get_annotations(old_session, eval_str=True)\n    sig = inspect.signature(old_session)\n    session.__signature__ = sig.replace(parameters=[p.replace(annotation=ann.get(p.name,p.annotation)) for p in sig.parameters.values()],return_annotation=ann.get("return",sig.return_annotation))\n    session.__annotations__ = ann')
    for path in ['uijeong_mcp.py','public_server.py','council_extensions.py','council_v29.py','release_info.py','v3_reliability.py']:
        py_compile.compile(str(ROOT/path),doraise=True)
    manifest_path=ROOT/'release_manifest.json'
    m=json.loads(manifest_path.read_text())
    runtime=[*ROOT.glob('*.py'),*ROOT.glob('data/*.json'),ROOT/'requirements.txt']
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(runtime) if p.is_file()}
    m.update(version='3.0.0-public.1',based_on='2.9.0-public.1',runtime_sha256=hashes,
             runtime_fingerprint=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
             runtime_protocol_claim='V3_RELIABILITY_RELEASE; CODE_TESTS_AND_LIVE_API_TESTS_REPORTED_SEPARATELY',
             deployment_performed_in_this_build=False)
    m.setdefault('profile_tool_counts',{}).update(public=21,full=44)
    for p in [*runtime,ROOT/'tests/test_v3_reliability.py',Path(__file__)]:
        if p.is_file():
            m.setdefault('files_sha256',{})[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'patched':True,'version':m['version'],'runtime_files':len(hashes),'public_tools':21}))


if __name__=='__main__':
    apply()
