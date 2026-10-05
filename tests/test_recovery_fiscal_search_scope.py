"""A bounded fiscal search must report requested expressions it did not scan."""
import asyncio
import datetime as dt

import finance_context as F
import v3_reliability as V


def test_accepted_extra_term_is_not_silently_lost_at_expression_limit(monkeypatch):
    monkeypatch.setenv("LOFIN_API_KEY", "SYNTHETIC_NOT_A_REAL_KEY")
    monkeypatch.setattr(V, "today", lambda: dt.date(2026, 10, 5))
    observed = []

    async def request(params):
        if "dbiz_nm" not in params:
            return {"rows": [{"fyr": "2026"}], "total_count": 1, "result_code": "INFO-000"}
        observed.append(params["dbiz_nm"])
        return {"rows": [], "total_count": 0, "result_code": "INFO-200"}

    monkeypatch.setattr(F, "_request", request)
    result = asyncio.run(V.finance_context("가상 사업", "수원시", 2026, 3,
                                         search_terms=["관련사업A", "관련사업B", "관련사업C"]))
    assert observed == ["가상 사업", "가상사업", "관련사업A", "관련사업B"]
    assert result["status"] == "PARTIAL"
    assert result["search_strategy"]["omitted_search_terms"] == ["관련사업C"]
    assert result["search_strategy"]["omission_reason"] == "SEARCH_EXPRESSION_LIMIT"
    assert result["coverage"]["search_terms_omitted"] is True
    assert result["coverage"]["has_unread_pages"] is False
    assert result["budget_basis"]["requested_stage_verified"] is False
