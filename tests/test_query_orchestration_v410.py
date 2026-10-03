"""Regression tests for v4.1 query decomposition and evidence-oriented orchestration."""
from datetime import date

import evidence_core as E
import integrated_ordinance as IO
import integrated_workflow as IW
import query_decomposition as Q


def test_complex_legal_question_is_decomposed():
    q="지방자치법 제130조 자문기관의 설치·운영 기준과 지방자치단체 조례로 시민회의·위원회를 둘 때 유의할 점"
    plan=Q.legal_search_plan(q,"전남광주통합특별시 서구",6)
    assert "지방자치법" in plan["law_names"]
    assert "제130조" in plan["article_refs"]
    assert "지방자치법" in plan["law_queries"]
    assert any(term in plan["ordinance_queries"] for term in ("시민회의","시민위원회","자문단","주민참여"))


def test_ai_council_terms_keep_exact_and_add_fallbacks():
    terms=Q.council_search_terms("AI 행정",3)
    assert terms[0]=="AI 행정"
    assert len(terms)<=3
    assert any(term in terms[1:] for term in ("AI","인공지능","생성형 AI","챗GPT"))


def test_exhaustive_intent_is_coverage_request_not_claim():
    plan=Q.decompose("착한 서구와 유사한 전국 모든 조례를 빠짐없이 찾아줘","광주 서구")
    assert plan["exhaustive_intent"] is True
    assert plan["coverage_contract"]["national_exhaustive"] is False
    assert plan["coverage_contract"]["semantic_exhaustive"] is False


def test_workflow_plan_contains_real_search_terms_not_only_placeholders():
    result=IW.local_workflow_plan(
        "지방자치법 제130조와 시민회의 관련 조례 및 최근 의회 질의를 검토해줘",
        jurisdiction="전남광주통합특별시 서구", as_of="2026-10-03",
        domains=["council","ordinance"])
    assert result["status"]=="PLAN_ONLY"
    assert result["decomposition"]["law_names"]
    council=next(x for x in result["steps"] if x["domain"]=="council")
    ordinance=next(x for x in result["steps"] if x["domain"]=="ordinance")
    assert council["arguments_template"]["keyword"]
    assert ordinance["arguments_template"]["law_queries"]==["지방자치법"]
    assert ordinance["query_plan"]["coverage_contract"]["national_exhaustive"] is False


def test_verified_event_exposes_matched_query_and_alternate_docids():
    turns=[
        {"idx":0,"label":"홍길동 위원","role":"member","text":"AI 행정 사업의 추진현황을 설명해 주십시오.","agenda":1,"act":"question"},
        {"idx":1,"label":"기획실장","role":"executive","text":"AI 활용 사업을 추진하고 있습니다.","agenda":1,"act":"answer"},
    ]
    record=E.make_record({"DOCID":"A","RASMBLY_ID":"062006","MTG_DE":"20261001",
                          "RASMBLY_NM":"전남광주통합특별시 서구의회","RASMBLY_NUMPR":"9",
                          "RASMBLY_SESN":"350","MINTS_ODR":"1","MTGNM":"기획총무위원회"},
                         turns,source="CLIK",source_kind="PUBLIC_API")
    record["aliases"]=[{"docid":"B","record_id":"other","source":"CLIK","provenance":{}}]
    record["dedup_basis"]="COMPLETE_MEETING_METADATA_AND_COMPLETE_PARSED_BODY"
    rows=E.record_events(record,"AI 행정","질의답변")
    assert len(rows)==1
    assert rows[0]["evidence_state"]=="VERIFIED_MATCH"
    assert rows[0]["matched_query"]=="AI 행정"
    assert rows[0]["alternate_docids"]==["B"]
    assert rows[0]["duplicate_reason"]=="COMPLETE_MEETING_METADATA_AND_COMPLETE_PARSED_BODY"


def test_evidence_complete_does_not_mean_semantic_exhaustive():
    result=E.evidence_status(items=1,attempted=1,succeeded=1)
    assert result["status"]=="COMPLETE"
    assert result["coverage"]["query_complete"] is True
    assert result["coverage"]["semantic_coverage"]=="INCOMPLETE_BY_DESIGN"
    assert result["coverage"]["is_exhaustive_council_archive"] is False


def test_ordinance_review_standard_compacts_large_payload():
    raw={
        "status":"review_completed","report_id":"R-test",
        "documents":[{"id":i,"text":"x"*5000} for i in range(20)],
        "selection_log":[{"i":i} for i in range(30)],
        "evidence":{f"e{i}":{"text":"근거"*3000} for i in range(30)},
        "quality_gate":{"blocking_or_pending_items":[str(i) for i in range(20)]},
    }
    result=IO._compact_review(raw,"standard",8)
    assert result["detail_level"]=="standard"
    assert len(result["documents"])<=8
    assert len(result["evidence"])<=8
    assert result["response_budget"]["evidence_omitted"]>0
    assert result["response_budget"]["lists_omitted"]>0
