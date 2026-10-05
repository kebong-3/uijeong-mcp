"""Independent recovery checks for incomplete legal scans and fiscal identity."""
import asyncio
from types import SimpleNamespace

import council_extensions as C
import finance_context as F
import integrated_ordinance as IO
import legal_context as L
import v3_reliability as V
from response_budget import apply_budget


def test_unread_legal_search_page_does_not_become_empty_local_search(monkeypatch):
    monkeypatch.setenv("LAW_OC", "SYNTHETIC_NOT_A_REAL_KEY")

    async def request(endpoint, params):
        if params["target"] == "law":
            return {"LawSearch": {"totalCnt": "0", "law": []}}
        return {"OrdinSearch": {"totalCnt": "101", "ordin": [
            {"자치법규ID": str(n), "자치법규일련번호": str(n + 1000),
             "자치법규명": f"서울특별시 중구 가상 지원 조례 {n}", "지자체기관명": "서울특별시 중구"}
            for n in range(100)
        ]}}

    monkeypatch.setattr(L, "_request", request)
    result = asyncio.run(V.legal_context("가상 지원", "수원시", include_articles=False))
    assert result["status"] == "PARTIAL"
    assert result["ordinances"] == []
    assert result["coverage"]["ordinance_search"] == "PARTIAL"
    assert result["coverage"]["has_unread_pages"] is True
    assert result["coverage"]["ordinance_attempts"][0]["api_total"] == 101
    assert result["legal_conclusion_verified"] is False


def test_fiscal_candidates_keep_account_snapshot_and_government_identity(monkeypatch):
    async def empty(*args, **kwargs):
        return {"status": "EMPTY", "items": [], "ordinances": []}

    for name in ("_bill_context", "_member_discovery", "_policy_context"):
        monkeypatch.setattr(C, name, empty)
    monkeypatch.setattr(L, "context", empty)
    monkeypatch.setattr(IO, "mention_context", empty)
    rows = [{
        "project_name": "문화예술 지원사업", "project_code": "SYNTHETIC-PROJECT",
        "fiscal_year": "2026", "execution_date": "20261003",
        "local_government": "서울특별시 종로구", "local_government_code": "1111000",
        "account": account, "budget_stage": "current", "amount_unit": "SOURCE_CONFIRMATION_REQUIRED",
        "budget_current_amount": amount, "same_project_verified": False,
    } for account, amount in [("일반회계", 100), ("특별회계", 200)]]

    async def finance(topic, council, year, limit, search_terms=None):
        return {"status": "PARTIAL", "items": rows} if search_terms else await empty()

    monkeypatch.setattr(F, "context", finance)

    async def evidence(**kwargs):
        return {"status": "PARTIAL", "items": [{
            "source_kind": "OFFICIAL_FETCHED", "event_id": "SYNTHETIC-EVENT",
            "speech": {"text": "청년을 대상으로 문화예술 지원사업을 운영합니다.",
                       "citation": {"source_kind": "OFFICIAL_FETCHED", "docid": "SYNTHETIC-DOC", "turn_index": 8}}
        }]}

    backend = SimpleNamespace(
        pick_council=lambda query: ("TEST", "서울특별시 종로구의회", None),
        council_evidence_bundle=evidence,
    )
    result = asyncio.run(V.context_pack(backend, "문화예술", fiscal_year=2026))
    review = result["linked_review"]
    index = review["candidate_index"]["budget"]
    assert len(index) == 2
    assert {row["account"] for row in index} == {"일반회계", "특별회계"}
    assert all(row["execution_date"] == "20261003" for row in index)
    assert all(row["local_government_code"] == "1111000" for row in index)
    relation = next(row for row in review["relationships"] if row["domain"] == "budget")
    for row in relation["result"]["items"]:
        arguments = row["recovery"]["arguments"]
        assert arguments["fiscal_year"] == 2026
        assert arguments["snapshot_date"] == row["execution_date"]
        assert arguments["council"] == row["local_government"]
        assert row["account"] in {"일반회계", "특별회계"}
        assert row["same_project_verified"] is False
        assert row["amount_unit"] == "SOURCE_CONFIRMATION_REQUIRED"
    assert review["budget"]["amounts_verified"] is False
    assert review["same_project_verified"] is False
    assert review["legal_approval"] is False
    assert result["ready_for_submission"] is False
    # An oversized unrelated field forces the wire reduction path. Distinct
    # accounting rows must still be distinguishable in the compact index.
    result["unbounded"] = [{"oversized": "x" * 50000} for _ in range(4)]
    reduced = apply_budget(result, 30000)
    assert reduced["linked_review"]["candidate_index"]["budget"] == index


def test_legal_recovery_does_not_skip_candidates_when_adapter_page_size_changes(monkeypatch):
    monkeypatch.setenv("LAW_OC", "SYNTHETIC_NOT_A_REAL_KEY")
    source_rows = [{"법령ID": str(n), "법령일련번호": str(n + 1000),
                    "법령명한글": f"가상 지원법 {n}"} for n in range(1, 102)]
    calls = []

    def payload(params):
        calls.append(dict(params))
        start = (params["page"] - 1) * params["display"]
        return {"LawSearch": {"totalCnt": "101", "law": source_rows[start:start + params["display"]]}}

    async def legacy_request(endpoint, params):
        if params["target"] == "ordin":
            return {"OrdinSearch": {"totalCnt": "0", "ordin": []}}
        return payload(params)

    async def document_request(self, endpoint, params, allow_stale=False):
        return payload(params), {"source_state": "fixture", "retrieved_at": "2026-10-05T00:00:00Z"}

    monkeypatch.setattr(L, "_request", legacy_request)
    monkeypatch.setattr(IO.LawClient, "request", document_request)

    class Registry:
        def __init__(self):
            self.tools = {}

        def tool(self, **metadata):
            def register(function):
                self.tools[metadata["name"]] = function
                return function
            return register

    registry = Registry()
    IO.register(registry)

    async def retrieve():
        result = await V.legal_context("가상 지원법", "", include_articles=False)
        recovery = result["coverage"]["law_coverage"]["recovery"][0]
        assert recovery["strategy"] == "RESTART_WITH_PUBLIC_SEARCH"
        arguments = dict(recovery["arguments"])
        # The legacy path scanned rows 1..20; the public adapter uses 100-row
        # pages. Its recovered first page must therefore retain row 21.
        arguments["offset"] = 20
        fetched = await registry.tools[recovery["tool"]](**arguments)
        return fetched

    fetched = asyncio.run(retrieve())
    assert calls[0]["target"] == "law" and calls[0]["display"] == 20
    assert calls[1]["target"] == "eflaw" and calls[1]["display"] == 100
    assert fetched["results"][0]["document_id"] == "21"
