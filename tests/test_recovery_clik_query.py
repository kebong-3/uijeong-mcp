"""Offline source-contract regression for CLIK's spaced content-query ERROR11.

Use the real client, quota/cache and public workflows; only the upstream HTTP
response is replaced. No live keys, API requests or invented production IDs.
"""
import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest

import council_v29 as V
import runtime_security as R
import uijeong_mcp as U


ORIGINAL = "소규모 공동주택"
COMPACT = "소규모공동주택"
PRIVATE_SENTINEL = "UPSTREAM_PRIVATE_VALUE_MUST_NOT_APPEAR"
BODY = (
    "<b>○김검증 위원</b> 소규모 공동주택 유지보수 지원계획과 관리현황은 어떻게 됩니까?<br>"
    "<b>○건축과장 이검증</b> 소규모 공동주택 유지보수 관리현황을 제출하고 지원계획을 검토하겠습니다.<br>"
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setattr(U, "API_KEY", "OFFLINE-TEST-AUTH-ONLY")
    monkeypatch.setattr(U, "PROFILE", "public")
    monkeypatch.setenv("UIJEONG_STATE_DB", str(tmp_path / "client.sqlite"))
    client = U.ClikClient()
    monkeypatch.setattr(U, "clik", client)
    council_id = U.pick_council("수원시")[0]

    class FixedDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 5)

    monkeypatch.setattr(V, "dt", SimpleNamespace(date=FixedDate))
    rows = [
        {"DOCID": "OFFLINE-2026", "RASMBLY_ID": council_id, "RASMBLY_NM": "수원시의회",
         "MTG_DE": "20261001", "MTGNM": "도시환경위원회", "MINTS_ODR": "1"},
        {"DOCID": "OFFLINE-2025", "RASMBLY_ID": council_id, "RASMBLY_NM": "수원시의회",
         "MTG_DE": "20250601", "MTGNM": "도시환경위원회", "MINTS_ODR": "1"},
    ]
    data = {"client": client, "council_id": council_id, "calls": [], "rows": rows,
            "primary": "ERROR11", "fallback": "SUCCESS"}

    async def raw(path, params):
        # Keep only noncredential request conditions even in the test capture.
        data["calls"].append({"endpoint": path, **{k: v for k, v in params.items() if k not in ("key", "type")}})
        if params.get("displayType") == "detail" and "docid" in params:
            row = next(x for x in data["rows"] if x["DOCID"] == params["docid"])
            return [{"RESULT_CODE": "SUCCESS", **row, "MINTS_HTML": BODY}]
        value = data["fallback"] if params.get("searchKeyword") == COMPACT else data["primary"]
        if isinstance(value, Exception):
            raise value
        if value is None:
            return []
        if value != "SUCCESS":
            return [{"RESULT_CODE": value, "RESULT_MESSAGE": PRIVATE_SENTINEL,
                     "key": PRIVATE_SENTINEL, "url": "https://example.invalid/?key=" + PRIVATE_SENTINEL}]
        return [{"RESULT_CODE": "SUCCESS", "TOTAL_COUNT": len(data["rows"]),
                 "LIST": [{"ROW": x} for x in data["rows"]]}]

    monkeypatch.setattr(client, "_raw_get", raw)
    return data


def arguments(source):
    return {"displayType": "list", "startCount": 0, "listCount": 100,
            "searchType": "MINTS_HTML", "searchKeyword": ORIGINAL,
            "rasmblyId": source["council_id"], "sort": "MTG_DE/DESC"}


async def workflow(name):
    if name == "recurring":
        return await U.council_recurring_issues(
            keyword=ORIGINAL, council="수원시", years=2, include_current_year=True,
            as_of="2026-10-05", date_from="2025-01-01", date_to="2026-10-05",
            min_years=2, top=1, max_docs_per_year=1,
        )
    if name == "peer":
        return await V._peer_cases(U, ORIGINAL, years=1, case_count=1, max_details=3)
    return await U.council_search_minutes(
        keyword=ORIGINAL, council="수원시", search_in="내용", date_from="2025-01-01",
        date_to="2026-10-05", limit=1,
    )


def test_recovery_uses_original_first_one_variant_and_normal_cache_quota(source):
    params = arguments(source)
    before = source["client"].budget_left()
    result = run(source["client"].get("minutes.do", **params))
    assert [x["searchKeyword"] for x in source["calls"]] == [ORIGINAL, COMPACT]
    assert params["searchKeyword"] == ORIGINAL
    assert before - source["client"].budget_left() == 2
    trace = result["query_recovery"]
    assert trace["attempts"] == [{"query": ORIGINAL, "code": "ERROR11"}, {"query": COMPACT, "code": "SUCCESS"}]
    assert trace["recovered"] is True and trace["same_result_set_verified"] is False
    assert trace["scope"] == {"endpoint": "minutes.do", "display_type": "list", "search_type": "MINTS_HTML",
                              "council_id": source["council_id"], "offset": 0, "list_count": 100, "sort": "MTG_DE/DESC"}
    compact = run(source["client"].get("minutes.do", **{**params, "searchKeyword": COMPACT}))
    assert "query_recovery" not in compact and len(source["calls"]) == 2
    repeated = run(source["client"].get("minutes.do", **params))
    assert len(source["calls"]) == 3 and source["calls"][-1]["searchKeyword"] == ORIGINAL
    assert repeated["query_recovery"]["recovered"] is True


@pytest.mark.parametrize('profile', ['full', 'lite', 'core', 'work'])
def test_legacy_profiles_keep_original_error_without_unreported_recovery(source, monkeypatch, profile):
    monkeypatch.setattr(U, 'PROFILE', profile)
    with pytest.raises(U.ClikError) as caught:
        run(source['client'].get('minutes.do', **arguments(source)))
    assert caught.value.code == 'ERROR11'
    assert caught.value.query_recovery is None
    assert [call['searchKeyword'] for call in source['calls']] == [ORIGINAL]


@pytest.mark.parametrize("name", ["recurring", "peer", "text"])
def test_public_recovery_keeps_original_scope_actual_evidence_and_partial(source, name):
    result = run(workflow(name))
    if name == "text":
        assert result.startswith("상태: PARTIAL")
        assert "OFFLINE-2026" in result
        assert ORIGINAL in result and COMPACT in result and "ERROR11" in result
        assert "20250101" in result and "20261005" in result
        return
    assert result["status"] == "PARTIAL"
    assert result["errors"] and all(x["code"] == "ERROR11" for x in result["errors"])
    for error in result["errors"]:
        trace = error["query_recovery"]
        assert trace["original_keyword"] == ORIGINAL and trace["fallback_keyword"] == COMPACT
        assert [x["code"] for x in trace["attempts"]] == ["ERROR11", "SUCCESS"]
        assert trace["local_filters"]["date_to"] <= "20261005"
    if name == "recurring":
        assert result["anchor"] == ORIGINAL and result["events_examined"] == 2
        assert all(x["status"] == "PARTIAL" for x in result["per_year"])
        assert all(x["coverage"][0]["query"] == ORIGINAL for x in result["per_year"])
        assert all(x["errors"][0]["query_recovery"]["scope"]["council_id"] == source["council_id"] for x in result["per_year"])
    else:
        assert result["topic"] == ORIGINAL and len(result["cases"]) == 1
        assert result["cases"][0]["docid"] == "OFFLINE-2026"
        assert result["cases"][0]["evidence"]["question"]
        assert result["coverage_card"]["list_calls"][0]["query_recovery"]["recovered"] is True


@pytest.mark.parametrize("name", ["recurring", "peer"])
@pytest.mark.parametrize("primary,status", [("SUCCESS", "EMPTY"), ("ERROR11", "PARTIAL")])
def test_empty_success_and_recovered_empty_have_distinct_status(source, name, primary, status):
    source.update(rows=[], primary=primary)
    result = run(workflow(name))
    assert result["status"] == status
    assert bool(result["errors"]) is (primary == "ERROR11")
    queries = [x["searchKeyword"] for x in source["calls"]]
    assert (COMPACT in queries) is (primary == "ERROR11")
    if primary == "SUCCESS":
        assert queries == [ORIGINAL]


@pytest.mark.parametrize("name", ["recurring", "peer", "text"])
def test_both_failures_retain_safe_codes_and_query_scope(source, name):
    source["fallback"] = "ERROR09"
    result = run(workflow(name))
    rendered = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    assert PRIVATE_SENTINEL not in rendered and "OFFLINE-TEST-AUTH-ONLY" not in rendered
    assert ORIGINAL in rendered and COMPACT in rendered
    assert "ERROR11" in rendered and "ERROR09" in rendered
    assert ("20251005" if name == "peer" else "20250101") in rendered and "20261005" in rendered
    if name == "text":
        assert result.startswith("상태: ERROR")
    else:
        assert result["status"] == "ERROR"
        assert all(x["code"] == "ERROR09" for x in result["errors"])
        assert all(x["query_recovery"]["recovered"] is False for x in result["errors"])
    assert len(source["calls"]) == (4 if name == "recurring" else 2)


@pytest.mark.parametrize("primary,overrides,path,code", [
    ("ERROR01", {}, "minutes.do", "ERROR01"),
    ("ERROR09", {}, "minutes.do", "ERROR09"),
    ("ERROR10", {}, "minutes.do", "ERROR10"),
    ("ERROR05", {}, "minutes.do", "ERROR05"),
    ("ERROR07", {}, "minutes.do", "ERROR07"),
    ("ERROR11", {"searchType": "ALL"}, "minutes.do", "ERROR11"),
    ("ERROR11", {"searchKeyword": "공동주택"}, "minutes.do", "ERROR11"),
    ("ERROR11", {}, "bill.do", "ERROR11"),
    ("ERROR11", {"displayType": "detail"}, "minutes.do", "ERROR11"),
    (None, {}, "minutes.do", "MALFORMED_RESPONSE"),
    (PRIVATE_SENTINEL, {}, "minutes.do", "UNKNOWN_RESPONSE"),
    (httpx.ReadTimeout(PRIVATE_SENTINEL), {}, "minutes.do", "TRANSPORT_ERROR"),
])
def test_other_failures_and_search_scopes_are_not_retried(source, primary, overrides, path, code):
    source["primary"] = primary
    with pytest.raises(U.ClikError) as caught:
        run(source["client"].get(path, **{**arguments(source), **overrides}))
    assert caught.value.code == code and caught.value.query_recovery is None
    assert len(source["calls"]) == 1
    assert PRIVATE_SENTINEL not in str(caught.value)


def test_recovery_cannot_bypass_the_local_call_budget(source, tmp_path):
    source["client"]._budget = R.SQLiteBudget(tmp_path / "one-call.sqlite", 1)
    with pytest.raises(U.ClikError) as caught:
        run(source["client"].get("minutes.do", **arguments(source)))
    assert len(source["calls"]) == 1 and source["client"].budget_left() == 0
    assert caught.value.code == "ERROR09"
    assert [x["code"] for x in caught.value.query_recovery["attempts"]] == ["ERROR11", "ERROR09"]
