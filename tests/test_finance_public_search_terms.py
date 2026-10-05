"""The advertised finance tool must execute its related-term fallback on the wire."""
import asyncio
import copy
import datetime as dt
from collections import OrderedDict

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

import finance_context as F
import uijeong_mcp as U
import v3_reliability as V
from public_server import public_function
from result_contract import wire_result


@pytest.fixture
def finance_server(monkeypatch):
    monkeypatch.setattr(V, "today", lambda: dt.date(2026, 10, 5))
    monkeypatch.setattr(V, "_CACHE", OrderedDict())
    monkeypatch.setattr(V, "_FLIGHTS", {})
    monkeypatch.setattr(V, "_LOOP", None)
    monkeypatch.setattr(F, "configuration", lambda: {"configured": True})
    monkeypatch.setattr(F, "context", V.finance_context)
    calls = []
    row = {"fyr": "2026", "exe_ymd": "20261005", "laf_cd": "4111000",
           "laf_hg_nm": "경기수원시", "dbiz_cd": "TEST_PROJECT",
           "dbiz_nm": "소규모 공동주택 활성화", "acnt_dv_cd": "100",
           "acnt_dv_nm": "일반회계", "bdg_cash_amt": 600000000,
           "ep_amt": 100000000, "cpl_amt": 600000000}

    async def request(params):
        calls.append(copy.deepcopy(params))
        rows = [row] if "dbiz_nm" not in params or params["dbiz_nm"] == "소규모 공동주택" else []
        return {"rows": copy.deepcopy(rows), "total_count": len(rows),
                "result_code": "INFO-000" if rows else "INFO-200"}

    monkeypatch.setattr(F, "_request", request)
    server = FastMCP("finance-public-search-terms")
    server.tool(name="council_finance_context")(
        wire_result(public_function(U.council_finance_context)))
    return server, calls


def arguments(**extra):
    return {"topic": "빌라가꿈관리소", "council": "수원시", "fiscal_year": 2026,
            "limit": 6, **extra}


def test_schema_advertises_optional_bounded_search_terms(finance_server):
    server, _ = finance_server
    schema = asyncio.run(server.list_tools())[0].inputSchema
    prop = schema["properties"]["search_terms"]
    array = next(item for item in prop["anyOf"] if item.get("type") == "array")
    assert "search_terms" not in schema.get("required", [])
    assert prop["default"] is None
    assert array["maxItems"] == 3
    assert (array["items"]["minLength"], array["items"]["maxLength"]) == (1, 100)


def test_public_sdk_queries_located_subject_after_exact_brand_miss(finance_server):
    server, calls = finance_server
    response = asyncio.run(server.call_tool(
        "council_finance_context", arguments(search_terms=["소규모 공동주택"])))
    result = response.structuredContent
    assert not response.isError
    assert result["status"] == "COMPLETE"
    assert [call.get("dbiz_nm") for call in calls] == [None, "빌라가꿈관리소", "소규모 공동주택"]
    assert result["query"]["topic"] == "빌라가꿈관리소"
    assert result["query"]["council"] == "경기도 수원시의회"
    assert result["search_strategy"]["progressive_widening"] is True
    item = result["items"][0]
    assert item["project_name"] == "소규모 공동주택 활성화"
    assert item["matched_query"] == "소규모 공동주택"
    assert item["match_status"] == "RELATED_PROJECT_CANDIDATE"
    assert item["same_project_verified"] is False
    assert item["appropriated_amount"] is None
    assert result["budget_basis"]["amount_verified"] is False


def test_existing_public_call_without_search_terms_keeps_exact_lookup(finance_server):
    server, calls = finance_server
    response = asyncio.run(server.call_tool("council_finance_context", arguments()))
    result = response.structuredContent
    assert result["status"] == "EMPTY"
    assert result["items"] == []
    assert [call.get("dbiz_nm") for call in calls] == [None, "빌라가꿈관리소"]


@pytest.mark.parametrize("terms", ["소규모 공동주택", ["a", "b", "c", "d"], ["x" * 101], [17], [""]])
def test_invalid_sdk_terms_are_rejected_before_upstream(finance_server, terms):
    server, calls = finance_server
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("council_finance_context", arguments(search_terms=terms)))
    assert calls == []


@pytest.mark.parametrize("terms", ["소규모 공동주택", ["a", "b", "c", "d"], ["x" * 101], [17], [" "]])
def test_direct_call_enforces_same_bounds(finance_server, terms):
    _, calls = finance_server
    result = asyncio.run(U.council_finance_context(**arguments(search_terms=terms)))
    assert result["status"] == "INVALID_INPUT"
    assert calls == []
