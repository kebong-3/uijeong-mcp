"""Regression coverage for recovered employee review flows; no live APIs."""
import asyncio
from types import SimpleNamespace

import pytest

import council_extensions as C
import finance_context as F
import integrated_ordinance as IO
import legal_context as L
import v3_reliability as V


def backend(monkeypatch, *, initial_status="EMPTY"):
    calls = []

    async def evidence(**kwargs):
        return {"status": "PARTIAL", "items": [{
            "source_kind": "OFFICIAL_FETCHED", "event_id": "evt_recovery",
            "speech": {"text": "홀몸 어르신을 대상으로 행복돌봄을 운영합니다.",
                       "citation": {"source_kind": "OFFICIAL_FETCHED", "docid": "D1", "turn_index": 8}}
        }]}

    async def bill(*args, **kwargs):
        return {"status": "EMPTY", "items": []}

    async def member(*args, **kwargs):
        calls.append("member")
        return {"status": "COMPLETE", "items": [{"name": "공식기록 후보"}]}

    async def policy(*args, **kwargs):
        calls.append("policy")
        return {"status": "EMPTY", "items": []}

    async def legal(*args, **kwargs):
        return {"status": initial_status, "ordinances": [], "errors": [{"code": "UPSTREAM_TIMEOUT"}]
                if initial_status == "ERROR" else []}

    async def finance(*args, search_terms=None, **kwargs):
        return ({"status": "COMPLETE", "items": [{"project_name": "홀몸 어르신 지원", "project_code": "P1",
                                                  "same_project_verified": False}]}
                if search_terms else {"status": initial_status, "items": []})

    async def mentioned(query, jurisdiction):
        return {"status": "PARTIAL", "items": [{"title": "가상 돌봄 지원 조례", "document_id": "L1",
                                                  "applicability_verified": False}]}

    monkeypatch.setattr(C, "_bill_context", bill)
    monkeypatch.setattr(C, "_member_discovery", member)
    monkeypatch.setattr(C, "_policy_context", policy)
    monkeypatch.setattr(L, "context", legal)
    monkeypatch.setattr(F, "context", finance)
    monkeypatch.setattr(IO, "mention_context", mentioned)
    return SimpleNamespace(pick_council=lambda _: ("X", "서울특별시 종로구의회", None),
                           council_evidence_bundle=evidence), calls


@pytest.mark.parametrize("initial_status", ["EMPTY", "ERROR"])
def test_followup_candidates_survive_initial_empty_or_failure(monkeypatch, initial_status):
    upstream, calls = backend(monkeypatch, initial_status=initial_status)
    result = asyncio.run(V.context_pack(upstream, "행복돌봄", fiscal_year=2026))
    assert result["finance_context"]["status"] == initial_status
    assert result["legal_and_ordinance_context"]["status"] == initial_status
    for domain in ("budget", "ordinance"):
        summary = result["linked_review"][domain]
        assert summary["status"] == "PARTIAL"
        assert summary["initial_status"] == initial_status
        assert summary["candidate_status"] == "CANDIDATES_FOUND"
        assert summary["initial_candidates"] == 0
        assert summary["discovered_candidates"] == 1
    assert result["linked_review"]["budget"]["amounts_verified"] is False
    assert result["linked_review"]["ordinance"]["applicability_verified"] is False
    assert result["linked_review"]["same_project_verified"] is False
    assert result["ready_for_submission"] is False
    if initial_status == "ERROR":
        assert result["legal_and_ordinance_context"]["errors"][0]["code"] == "UPSTREAM_TIMEOUT"
    assert calls == []


@pytest.mark.parametrize("member,policy,expected", [
    (False, False, []), (True, False, ["member"]),
    (False, True, ["policy"]), (True, True, ["member", "policy"]),
])
def test_background_requests_are_opt_in_and_traceable(monkeypatch, member, policy, expected):
    upstream, calls = backend(monkeypatch)
    result = asyncio.run(V.context_pack(upstream, "행복돌봄", include_legal=False, include_finance=False,
                                      include_member_records=member, include_policy_background=policy))
    assert sorted(calls) == sorted(expected)
    for layer, enabled in (("member_record_discovery", member), ("policy_background", policy)):
        assert (result[layer]["status"] == "SKIPPED") is (not enabled)
        if not enabled:
            assert result[layer]["reason"] == "NOT_REQUESTED"
    for domain in ("budget", "ordinance"):
        assert result["linked_review"][domain]["status"] == "SKIPPED"
        assert result["linked_review"][domain]["candidate_status"] == "NOT_REQUESTED"
