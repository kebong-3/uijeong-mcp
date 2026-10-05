"""Large real-shaped comparisons must survive the public MCP response limit."""
import asyncio
import copy
from datetime import date
import json

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import integrated_ordinance as O
from integrated_transport import Registry
from jachi.analysis import compare_documents
from jachi.models import Article, Document


@pytest.fixture
def comparison_server(monkeypatch):
    docs = {}
    for identifier, city, verb in [("123", "가상시", "지원할 수 있다"), ("456", "시험시", "지원하여야 한다")]:
        articles = [Article(
            key=f"main:제{n}조", label=f"제{n}조", title=f"지원사업 {n}",
            text=f"제{n}조(지원사업 {n}) " + f"① 청년 지원사업 대상자를 선정하고 {n}만원을 {verb}. " * 32,
        ) for n in range(1, 13)]
        docs[identifier] = Document(
            kind="ordinance", document_id=identifier, title=f"{city} 가상 지원 조례", jurisdiction=city,
            version=str(int(identifier) + 1000), source_state="fixture", version_scope="version",
            effective_date="20260101", source_url=f"https://www.law.go.kr/ordinInfoP.do?ordinSeq={identifier}",
            articles=articles, warnings=["원문 표제로 조문 식별"] * 12,
        )
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_document(self, reference):
            calls.append(reference.model_dump())
            return docs[reference.document_id]

    monkeypatch.setattr(O, "LawClient", Client)
    server = FastMCP("bounded-ordinance-comparison")
    O.register(Registry(server))
    return server, docs, calls


def arguments(**extra):
    return {"baseline":{"kind":"ordinance", "document_id":"123"},
            "comparisons":[{"kind":"ordinance", "document_id":"456"}],
            "as_of":"2026-10-05", **extra}


def test_minimum_two_documents_return_real_findings_under_public_limit(comparison_server):
    server, docs, _ = comparison_server
    full = compare_documents(docs["123"], [docs["456"]], date(2026, 10, 5))
    assert len(json.dumps(full, ensure_ascii=False)) > 30000
    result = asyncio.run(server.call_tool("ordinance_compare", arguments()))
    data = result.structuredContent
    assert not result.isError
    assert data["status"] == "PARTIAL"
    assert len(json.dumps(data, ensure_ascii=False)) < 30000
    assert data["coverage"]["total_alignments"] == 12
    assert data["coverage"]["returned_alignments"] > 0
    assert data["coverage"]["output_complete"] is False
    assert data["coverage"]["analysis_comparison_complete"] is True
    assert data["baseline"]["content_hash"] == docs["123"].content_hash
    assert data["baseline"]["warning_coverage"]["unique_warnings"] == 1
    first = data["comparisons"][0]["alignments"][0]
    assert first["category"] == full["comparisons"][0]["alignments"][0]["category"]
    assert first["baseline_candidates"][0]["semantic_flags"] == full["comparisons"][0]["alignments"][0]["baseline_candidates"][0]["semantic_flags"]
    assert data["alignment_counts"][first["category"]] > 0
    assert data["legal_approval"] is False
    assert data["equivalence_verified"] is False
    assert data["ready_for_submission"] is False


def test_generated_continuation_covers_every_alignment_once(comparison_server):
    server, docs, _ = comparison_server

    async def traverse():
        current = arguments(limit=5, max_chars=1500)
        seen = []
        pages = []
        for _ in range(15):
            response = await server.call_tool("ordinance_compare", current)
            assert not response.isError
            page = response.structuredContent
            assert len(json.dumps(page, ensure_ascii=False)) < 30000
            seen.extend(row["peer"]["article_key"] for comparison in page["comparisons"]
                        for row in comparison["alignments"])
            pages.append(page)
            followup = page["continuation"]
            if followup is None:
                break
            assert followup["tool"] == "ordinance_compare"
            current = followup["arguments"]
            assert current["baseline"]["mst"] == docs["123"].version
            assert current["comparisons"][0]["mst"] == docs["456"].version
            assert current["expected_hashes"] == [docs["123"].content_hash, docs["456"].content_hash]
        return seen, pages

    seen, pages = asyncio.run(traverse())
    assert seen == [article.key for article in docs["456"].articles]
    assert len(seen) == len(set(seen))
    assert pages[-1]["coverage"]["next_offset"] is None
    assert len(pages) > 1


def test_excerpt_recovery_returns_exact_full_original_article(comparison_server):
    server, docs, _ = comparison_server
    before = copy.deepcopy(docs["456"].model_dump())

    async def recover():
        response = await server.call_tool("ordinance_compare", arguments())
        peer = response.structuredContent["comparisons"][0]["alignments"][0]["peer"]
        location = peer["excerpt_location"]
        raw = docs["456"].articles[location["item_offset"]].text
        assert location["excerpt_only"] is True
        assert peer["text"] == raw[location["char_start"]:location["char_end"]]
        retrieval = peer["recovery"]
        full = await server.call_tool(retrieval["tool"], retrieval["arguments"])
        assert not full.isError
        assert full.structuredContent["summary"]["content_hash"] == retrieval["expected_content_hash"]
        assert full.structuredContent["articles"][0]["text"] == raw

    asyncio.run(recover())
    assert docs["456"].model_dump() == before


def test_changed_source_cannot_be_combined_with_prior_page(comparison_server):
    server, docs, _ = comparison_server

    async def run():
        first = await server.call_tool("ordinance_compare", arguments())
        next_arguments = first.structuredContent["continuation"]["arguments"]
        docs["456"].articles[0].text += " 원문 수정 사항."
        second = await server.call_tool("ordinance_compare", next_arguments)
        assert second.isError
        assert second.structuredContent["code"] == "source_changed"
        assert "comparisons" not in second.structuredContent

    asyncio.run(run())


def test_unprocessed_comparisons_are_not_reported_as_complete(comparison_server, monkeypatch):
    server, _, _ = comparison_server
    actual = O.compare_documents

    def limited(baseline, others, as_of):
        return actual(baseline, others, as_of, max_pairs=1)

    monkeypatch.setattr(O, "compare_documents", limited)
    result = asyncio.run(server.call_tool("ordinance_compare", arguments()))
    data = result.structuredContent
    assert not result.isError
    assert data["status"] == "PARTIAL"
    assert data["coverage"]["analysis_comparison_complete"] is False
    assert data["coverage"]["unprocessed_articles"] == 12
    assert data["alignment_counts"]["not_processed_budget"] == 12
    row = data["comparisons"][0]["alignments"][0]
    assert row["category"] == "not_processed_budget"
    assert row["baseline_candidates"] == []
    assert row["peer"]["recovery"]["tool"] == "ordinance_get_document"


@pytest.mark.parametrize("extra", [{"offset":-1}, {"limit":0}, {"max_chars":99}, {"expected_hashes":["x"]}])
def test_invalid_public_page_arguments_do_not_fetch_documents(comparison_server, extra):
    server, _, calls = comparison_server
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("ordinance_compare", arguments(**extra)))
    assert calls == []
