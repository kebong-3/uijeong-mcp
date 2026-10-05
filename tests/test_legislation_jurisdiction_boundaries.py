"""A mixed search response never makes a neighboring government's ordinance local."""
import asyncio

import legal_context as L
import uijeong_mcp as U


def test_title_local_and_body_foreign_results_are_classified_per_row(monkeypatch):
    calls = []

    async def request(mode, params):
        calls.append(dict(params))
        local = params["search"] == 1
        row = {"자치법규명": "수원시 소규모 공동주택관리 지원 조례" if local else "용인시 소규모 공동주택관리 지원 조례",
               "자치법규ID": "LOCAL123" if local else "PEER456",
               "자치법규일련번호": "111" if local else "222",
               "지자체기관명": "경기도 수원시" if local else "경기도 용인시"}
        return {"OrdinSearch": {"totalCnt": 1, "law": [row]}}

    monkeypatch.setattr(L, "_request", request)
    result = asyncio.run(U.council_legislation_context(
        "공동주택", council="수원시", jurisdiction="수원특례시", include_articles=False))
    assert any(params["search"] == 2 for params in calls)
    assert [row["document_id"] for row in result["local_ordinances"]] == ["LOCAL123"]
    assert [row["document_id"] for row in result["ordinances"]] == ["LOCAL123"]
    peers = result["nationwide_ordinance_candidates"]
    assert [row["document_id"] for row in peers] == ["PEER456"]
    assert peers[0]["match_status"] == "NATIONWIDE_FUNCTIONAL_CANDIDATE"
    assert peers[0]["role"] == "COMPARATIVE_DISCOVERY_ONLY"


def test_ambiguous_explicit_legal_jurisdiction_rejects_before_search(monkeypatch):
    calls = []

    async def request(*args, **kwargs):
        calls.append(True)
        raise AssertionError("ambiguous municipality must not query upstream")

    monkeypatch.setattr(L, "_request", request)
    result = asyncio.run(U.council_legislation_context(
        "공동주택", council="서울특별시 중구", jurisdiction="중구", include_articles=False))
    assert result["status"] == "INVALID_INPUT"
    assert result["jurisdiction_resolution"]["state"] == "ambiguous"
    assert len(result["jurisdiction_resolution"]["candidates"]) > 1
    assert calls == []
