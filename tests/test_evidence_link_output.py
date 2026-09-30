import asyncio
from evidence_links import attach_source_links, safe_reference
from result_contract import wire_result
from integrated_transport import wrap

LAW="https://www.law.go.kr/ordinInfoP.do?ordinSeq=123456"
MINUTES="https://www.gjsc.or.kr/record/recordView.do?key=ABC123"
CATALOG="https://www.data.go.kr/data/15138857/openapi.do"

def test_clickable_document_and_metadata_links_keep_scope():
    result=attach_source_links({"items":[{"title":"평생교육 조례","source_url":LAW},
        {"title":"예산 심사 회의록","source_link":{"url":MINUTES,"status":"PROVIDED_NOT_FETCHED"}},
        {"source_url":CATALOG}],"dataset_url":"https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=ABC"})
    links={r["url"]:r for r in result["source_links"]}
    assert links[LAW]["direct_document"] is True
    assert links[MINUTES]["status"]=="PROVIDED_NOT_FETCHED"
    assert links[CATALOG]["kind"]=="CATALOG_METADATA"
    assert links[CATALOG]["direct_document"] is False
    assert all(r["markdown"].startswith("[") for r in links.values())

def test_credentials_and_machine_endpoints_never_exposed_as_viewers():
    for url in ["https://www.law.go.kr/DRF/lawService.do?OC=SECRET",
        "https://www.lofin365.go.kr/lf/hub/QWGJK?Key=SECRET",
        "https://example.go.kr/?serviceKey=SECRET","javascript:alert(1)",
        "https://user:pass@example.go.kr/x"]:
        assert safe_reference(url) is None
        assert "source_links" not in attach_source_links({"source_url":url})

def test_unresolved_clik_original_uses_honest_search_reference():
    link=attach_source_links({"items":[{"source":"CLIK","docid":"CLIK123","provenance":{}}]})["source_links"][0]
    assert link["kind"]=="OFFICIAL_SEARCH"
    assert link["direct_document"] is False

def test_both_mcp_boundaries_return_clickable_structured_references():
    async def source():
        return {"status":"COMPLETE","summary":{"title":"평생교육 조례","source_url":LAW}}
    for decorator in (wire_result,wrap):
        result=asyncio.run(decorator(source)())
        assert result.structuredContent["source_links"][0]["url"]==LAW

def test_link_limit_reports_omissions():
    result=attach_source_links({"items":[{"source_url":f"https://www.law.go.kr/ordinInfoP.do?ordinSeq={i}"} for i in range(30)]})
    assert len(result["source_links"])==16
    assert result["link_guidance"]["links_omitted"] is True

def test_original_link_in_provenance_prevents_search_fallback():
    result=attach_source_links({"items":[{"source":"CLIK","docid":"CLIK123","provenance":{"source_url":MINUTES}}]})
    assert len(result["source_links"])==1
    assert result["source_links"][0]["url"]==MINUTES

def test_dataset_dedup_preserves_project_lookup_fields():
    url="https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=ABC"
    result=attach_source_links({"dataset_url":url,"items":[{"source_link":{
        "url":url,"kind":"OFFICIAL_DATASET","lookup":{"project_code":"VERIFIED_API_ID"}}}]})
    assert len(result["source_links"])==1
    assert result["source_links"][0]["lookup"]["project_code"]=="VERIFIED_API_ID"
