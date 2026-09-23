"""Offline contract tests for OpenAI standard search/fetch compatibility."""
import asyncio

import openai_compat as O


OFFICIAL_URL = "https://www.gjsc.or.kr/record/recordView.do?key=ABC123"


class FakeBackend:
    async def council_evidence_bundle(self, **kwargs):
        assert kwargs["mode"] == "발언"
        assert kwargs["max_docs"] == 4
        return {
            "status": "COMPLETE",
            "items": [{
                "kind": "발언",
                "docid": "ABC123",
                "metadata": {
                    "council_name": "전남광주통합특별시 서구의회",
                    "meeting_date": "20260901",
                    "meeting_name": "사회도시위원회",
                },
                "question": {
                    "turn_index": 7,
                    "citation": {"citation_url": OFFICIAL_URL},
                },
                "answers": [],
                "speech": None,
                "provenance": {"source": "SEOGU_SITE", "citation_url": OFFICIAL_URL},
            }],
        }

    async def council_read_source(self, **kwargs):
        assert kwargs["ref"] == "site:ABC123"
        assert kwargs["start_turn"] == 5
        return {
            "status": "COMPLETE",
            "meta": {
                "council_name": "전남광주통합특별시 서구의회",
                "meeting_date": "20260901",
                "meeting_name": "사회도시위원회",
            },
            "source_link": {"url": OFFICIAL_URL, "status": "FETCHED_MATCHED"},
            "source_url": OFFICIAL_URL,
            "turns": [
                {"idx": 5, "label": "위원", "speech_context": "질의", "text": "경로당 운영 현황을 질의합니다."},
                {"idx": 6, "label": "과장", "speech_context": "답변", "text": "운영 현황을 설명드리겠습니다."},
                {"idx": 7, "label": "위원", "speech_context": "질의", "text": "추가 개선계획을 질의합니다."},
            ],
            "next_start_turn": None,
        }


def test_search_returns_required_contract_and_absolute_url():
    tools = O.build_tools(FakeBackend())
    result = asyncio.run(tools["search"]("광주 서구 경로당 최근 회의록"))
    dumped = result.model_dump()
    assert set(dumped) == {"results"}
    assert len(dumped["results"]) == 1
    item = dumped["results"][0]
    assert set(item) == {"id", "title", "url"}
    assert item["id"].startswith("uc1_")
    assert item["url"] == OFFICIAL_URL
    assert "사회도시위원회" in item["title"]


def test_fetch_roundtrip_returns_required_contract():
    tools = O.build_tools(FakeBackend())
    search_result = asyncio.run(tools["search"]("광주 서구 경로당 최근 회의록"))
    ident = search_result.results[0].id
    fetched = asyncio.run(tools["fetch"](ident)).model_dump()
    assert {"id", "title", "text", "url"} <= set(fetched)
    assert fetched["id"] == ident
    assert fetched["url"] == OFFICIAL_URL
    assert "경로당 운영 현황" in fetched["text"]
    assert fetched["metadata"]["matched_turn"] == 7


def test_fetch_rejects_tampered_or_external_ids():
    tools = O.build_tools(FakeBackend())
    try:
        asyncio.run(tools["fetch"]("not-a-valid-id"))
    except ValueError:
        pass
    else:
        raise AssertionError("invalid ID must fail")
