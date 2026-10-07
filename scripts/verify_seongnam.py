"""Bounded live acceptance against the existing public MCP, not a load test.

Only public read-only calls are sent. IDs for continuation come from this run.
Currency-unit verification is a separate, explicit limitation even when the
fail-closed numeric safety test passes. No government decision is certified.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import time
import urllib.request

ENDPOINT = 'https://uijeong-mcp.onrender.com/mcp'
QUESTION = '성남시 스마트도시 관련 조례, 2026년 예산현액·본예산/추경 구분, 2026년 의회 발언을 찾아 서로 연결하고 MCP 품질을 검증한다.'
NATURAL = '성남시의회 2026 스마트도시 스마트그린 안전쉼터 이군수'
DOCUMENT = 'CLIKC2912207453426003'


def normalize(response):
    result = response.get('result') or {}
    value = result.get('structuredContent')
    if isinstance(value, dict):
        return value
    for block in result.get('content') or []:
        if block.get('type') == 'text':
            try:
                value = json.loads(block.get('text', ''))
                if isinstance(value, dict):
                    return value
            except (ValueError, TypeError):
                pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--expect-version', default='4.1.6-public.1')
    parser.add_argument('--expect-fingerprint', default='')
    parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    root = Path(args.output_dir); root.mkdir(parents=True, exist_ok=True)
    records, checks = [], {}
    def save(name, data):
        (root / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def rpc(label, method, params):
        start = time.monotonic()
        body = {'jsonrpc': '2.0', 'id': len(records)+1, 'method': method, 'params': params}
        try:
            req = urllib.request.Request(ENDPOINT, data=json.dumps(body, ensure_ascii=False).encode(),
                headers={'Content-Type':'application/json', 'Accept':'application/json, text/event-stream'})
            with urllib.request.urlopen(req, timeout=85) as r:
                response = json.load(r)
            data = normalize(response)
        except Exception as exc:
            response = {'transport_error_type': type(exc).__name__}
            data = {}
        record = {'label': label, 'request': body, 'response': response, 'seconds': round(time.monotonic()-start, 2),
                  'checked_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        save(label, record)
        records.append({'label':label, 'status':data.get('status'), 'seconds':record['seconds'],
                        'isError': bool((response.get('result') or {}).get('isError')),
                        'transport_error': response.get('transport_error_type')})
        print(json.dumps(records[-1], ensure_ascii=False), flush=True)
        return data
    def call(label, name, arguments):
        return rpc(label, 'tools/call', {'name':name, 'arguments':arguments})
    rpc('initialize', 'initialize', {'protocolVersion':'2025-11-25','capabilities':{},
        'clientInfo':{'name':'seongnam-acceptance', 'version':'1.0'}})
    deadline = time.monotonic() + max(0, min(args.wait_seconds, 420))
    status = call('runtime', 'council_status', {'live':False})
    attempt = 0
    while status.get('version') != args.expect_version and time.monotonic() < deadline:
        time.sleep(15); attempt += 1
        status = call('runtime-wait-'+str(attempt), 'council_status', {'live':False})
    checks['expected_version'] = status.get('version') == args.expect_version
    checks['release_manifest'] = status.get('release_verification', {}).get('status') == 'MATCH'
    if args.expect_fingerprint:
        checks['expected_runtime_fingerprint'] = status.get('runtime_fingerprint') == args.expect_fingerprint
    if not checks['expected_version']:
        save('summary', {'status':'DEPLOYMENT_NOT_OBSERVED','checks':checks,'records':records})
        return 2
    listing = rpc('tools', 'tools/list', {})
    schemas = {t['name']:t.get('inputSchema', {}) for t in listing.get('tools', [])}
    checks['same_40_tools'] = len(schemas) == 40
    checks['schema_public_cap'] = schemas.get('council_evidence_bundle', {}).get('properties', {}).get('max_docs', {}).get('maximum') == 6
    checks['schema_ordinance_cap'] = schemas.get('ordinance_get_document', {}).get('properties', {}).get('max_chars', {}).get('maximum') == 5000
    plan = call('test01-query','local_workflow_plan',{'question':QUESTION,'jurisdiction':'성남시','fiscal_year':2026,'as_of':'2026-10-07'})
    decomposition = plan.get('decomposition', {})
    checks['01_query_clean'] = decomposition.get('topic_entities') == ['스마트도시'] and decomposition.get('search_synonyms') == ['스마트시티']
    finance = call('test02-finance-union','council_finance_context',{'topic':'스마트도시','council':'성남시','fiscal_year':2026,'snapshot_date':'20261007','limit':20})
    rows = finance.get('items') or []
    terms = {x.get('term'):x.get('matched_local_government',0) for x in finance.get('search_strategy', {}).get('attempts', [])}
    identities = [(r.get('project_code'),r.get('local_government_code'),r.get('account')) for r in rows]
    checks['02_finance_synonym_union'] = terms.get('스마트도시',0) >= 3 and terms.get('스마트시티',0) >= 2 and len(identities) == len(set(identities)) and len(rows)>=5
    original = call('test03-finance-stage','council_finance_context',{'topic':'스마트도시','council':'성남시','fiscal_year':2026,'snapshot_date':'20261007','budget_stage':'original','limit':10})
    basis = original.get('budget_basis') or {}
    checks['03_fiscal_stage_preserved'] = basis.get('requested_stage') == 'original' and basis.get('returned_stage') == 'current' and basis.get('requested_stage_verified') is False
    checks['04_unit_fail_closed'] = bool(rows) and finance.get('unit_metadata', {}).get('unit_verified') is False and finance.get('numeric_normalization') == 'BLOCK_NUMERIC_NORMALIZATION'
    exact = call('test05-ordinance-exact','ordinance_search',{'query':'성남시 스마트도시 조성 및 운영 조례','jurisdiction':'성남시','limit':5,'max_pages':1})
    first = next(iter(exact.get('results') or []), {})
    checks['05_exact_title_first'] = str(first.get('document_id')) == '2152882' and str(first.get('mst')) == '2013375' and first.get('title_match_score') == 100
    local = call('test06-ordinance-local','ordinance_search',{'query':'스마트도시','jurisdiction':'성남시','limit':5,'max_pages':1})
    checks['06_jurisdiction_upstream'] = bool(local.get('results')) and local.get('search_strategy', {}).get('jurisdiction_applied_upstream') is True and all('성남시' in r.get('jurisdiction','') for r in local.get('results',[]))
    natural = call('test07-natural-search','search',{'query':NATURAL})
    result = next((r for r in natural.get('results', []) if '이군수' in r.get('title','')), None)
    fetched = call('test07-fetch','fetch',{'id':result['id']}) if result else {}
    checks['07_natural_search_passage'] = bool(result) and DOCUMENT in json.dumps(fetched, ensure_ascii=False) and '20260904' in re.sub(r'[-.]','',json.dumps(fetched,ensure_ascii=False))
    source = call('test08-source','council_read_source',{'ref':DOCUMENT,'keyword':'스마트도시','max_turns':50,'max_chars':16000})
    turns = source.get('turns') or []
    paired = any(t.get('label') == '이군수 위원' and i+1<len(turns) and turns[i+1].get('label') == 'AI혁신국장 차광승' and '예, 맞습니다.' in turns[i+1].get('text','') for i,t in enumerate(turns))
    checks['08_inline_speaker_separated'] = paired and all('○AI혁신국장' not in t.get('text','') for t in turns)
    checks['source_spans_retained'] = any(t.get('source_span') for t in turns)
    checks['public_document_link_preserved'] = bool(source.get('attachment_url') or source.get('canonical_public_url')) and '[REDACTED]' not in (source.get('attachment_url') or source.get('canonical_public_url') or '')
    dept = call('test09-department','council_department_brief',{'department':'스마트도시과','council':'성남시','date_from':'2026-01-01','date_to':'2026-10-07','max_docs':6,'limit':3})
    checks['09_department_evidence'] = any(dept.get(k) for k in ('answered_items','unanswered_questions','other_mention_items'))
    checks['department_snapshot_stored'] = bool(dept.get('snapshot_id'))
    minutes = call('test10-minutes-dedup','council_search_minutes',{'keyword':'스마트도시','council':'성남시','date_from':'2026-01-01','date_to':'2026-10-07','search_in':'내용','limit':6})
    text = minutes.get('result','')
    display_lines = [line for line in text.splitlines() if line.startswith('- ') and 'docid=' in line]
    meeting_titles = [line.split('docid=')[0] for line in display_lines]
    checks['10_meeting_duplicate_group'] = bool(display_lines) and len(meeting_titles)==len(set(meeting_titles)) and ('alternate_docids' in text)
    bundle = call('test11-large-bundle','council_evidence_bundle',{'keyword':'스마트도시','council':'성남시','date_from':'2026-01-01','date_to':'2026-10-07','max_docs':6,'limit':10,'search_terms':['스마트시티','스마트그린']})
    continuation = bundle.get('continuation') or {}
    next_offset = bundle.get('next_item_offset')
    next_page = call('test11-continuation','council_get_evidence',{'snapshot_id':bundle['snapshot_id'],'item_offset':next_offset,'limit':3}) if bundle.get('snapshot_id') and next_offset is not None else {}
    checks['11_representative_items_survive'] = bool(bundle.get('snapshot_id')) and len(bundle.get('items', [])) >= 3 and len(json.dumps(bundle,ensure_ascii=False))<=30000
    ids = {r.get('event_id') for r in bundle.get('items',[])}
    checks['11_snapshot_continuation'] = bool(next_page.get('items')) and not ids.intersection(r.get('event_id') for r in next_page.get('items',[]))
    context = call('automatic-quality-gate','council_context_pack',{'topic':'스마트도시','council':'성남시','date_from':'2026-01-01','date_to':'2026-10-07','fiscal_year':2026,'max_docs':2,'include_public_data':False})
    gate = context.get('final_quality_gate') or {}
    checks['automatic_numeric_gate'] = gate.get('numeric_normalization')=='BLOCK_NUMERIC_NORMALIZATION' and gate.get('verified_facts') is False and bool(gate.get('required_answer_qualifiers'))
    checks['candidate_relationship_not_certified'] = (gate.get('policy_entity') or {}).get('same_project_verified') is False and context.get('ready_for_submission') is False
    health = call('test12-health','council_status',{'test_council':'성남시','live':True})
    checks['12_runtime_and_query_health_separate'] = health.get('runtime_status')=='HEALTHY' and health.get('deployment_status')=='MATCH' and bool(health.get('integration_status'))
    budget_status = call('budget-check-state','budget_api_status',{})
    checks['budget_check_state_explicit'] = budget_status.get('check_state') in ('NO_CHECK_SINCE_RESTART','CHECKS_RECORDED')
    try:
        with urllib.request.urlopen(ENDPOINT.replace('/mcp','/healthz'),timeout=20) as r:
            checks['health_http_200'] = r.status == 200
    except Exception:
        checks['health_http_200'] = False
    report = {'status':'PASS' if all(checks.values()) else 'REVIEW_REQUIRED','checks':checks,
        'passed':sum(bool(v) for v in checks.values()),'total':len(checks),'records':records,
        'deployment_commit':status.get('deployment_commit'),'version':status.get('version'),
        'runtime_fingerprint':status.get('runtime_fingerprint'), 'verified_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'scope':'12 requested scenarios plus transport/schema/continuation controls. Not exhaustive or a concurrency/load test.',
        'official_money_unit_verified':False,
        'remaining_limitations':['QWGJK field units not confirmed in retrieved official specification; raw values only.',
            'MCP response qualifiers cannot compel every downstream language model to comply.',
            'Search synonyms and list-metadata duplicate groups do not certify project or document-body equivalence.']}
    save('summary',report)
    print(json.dumps({'status':report['status'],'checks':checks},ensure_ascii=False),flush=True)
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
