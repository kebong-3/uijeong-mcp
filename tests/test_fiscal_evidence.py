import asyncio
import datetime as dt
import copy
import pytest
import finance_context as F
import v3_reliability as V
from budget_evidence import MAX_REQUESTS

def row(date="20260930", **extra):
    return {"fyr":"2026","exe_ymd":date,"laf_cd":"2912000","laf_hg_nm":"전남광주서구",
            "dbiz_cd":"360000020163001D","dbiz_nm":"세상에서가장큰대학서구운영","acnt_dv_cd":"100","acnt_dv_nm":"일반회계",
            "bdg_cash_amt":196162000,"ep_amt":120489330,"cpl_amt":176948000,**extra}

def envelope(rows=(), total=None):
    return {"result_code":"INFO-000" if rows else "INFO-200","message":"","rows":list(rows),
            "total_count":len(rows) if total is None else total}

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("LOFIN_API_KEY","SYNTHETIC_NOT_A_REAL_KEY")
    monkeypatch.setattr(V,"today",lambda:dt.date(2026,10,1))
    return monkeypatch

def call(topic="세상에서 가장 큰 대학", **kwargs):
    return asyncio.run(V.finance_context(topic,"광주 서구",2026,5,**kwargs))

def test_date_availability_then_compact_name_query(setup):
    calls=[]
    async def request(params):
        calls.append(copy.deepcopy(params))
        if params["exe_ymd"]=="20261001": return envelope()
        if "dbiz_nm" not in params: return envelope([row()])
        return envelope([row()]) if params["dbiz_nm"]=="세상에서가장큰대학" else envelope()
    setup.setattr(F,"_request",request)
    result=call()
    assert result["status"]=="COMPLETE"
    assert result["query"]["snapshot_date"]=="20260930"
    assert result["query"]["requested_snapshot_date"]=="20261001"
    assert result["date_resolution"]["fallback_used"] is True
    assert [p.get("dbiz_nm") for p in calls]==[None,None,"세상에서 가장 큰 대학","세상에서가장큰대학"]
    item=result["items"][0]
    assert item["budget_current_amount"]==196162000
    assert item["unspent_current_amount"]==75672670
    assert item["appropriated_amount"] is None
    assert item["unverified_fields"]["cpl_amt"]==176948000
    assert item["source_link"]["lookup"]["project_code"]=="360000020163001D"
    assert item["source_link"]["direct_document"] is False

def test_keyword_miss_never_moves_to_older_project_date(setup):
    calls=[]
    async def request(params):
        calls.append(params)
        return envelope([row("20261001")]) if "dbiz_nm" not in params else envelope()
    setup.setattr(F,"_request",request)
    result=call("해당없음")
    assert result["status"]=="EMPTY"
    assert result["query"]["snapshot_date"]=="20261001"
    assert all(p["exe_ymd"]=="20261001" for p in calls)

def test_date_error_never_becomes_empty_or_fallback(setup):
    calls=[]
    async def request(params):
        calls.append(params)
        raise F.FinanceContextError("LOFIN_ERROR-300")
    setup.setattr(F,"_request",request)
    result=call()
    assert result["status"]=="ERROR"
    assert len(calls)==1
    assert result["date_resolution"]["date_attempts"]==[]

def test_no_available_date_bounded_and_not_zero_budget(setup):
    calls=[]
    async def request(params):
        calls.append(params)
        return envelope()
    setup.setattr(F,"_request",request)
    result=call()
    assert result["status"]=="EMPTY"
    assert result["query"]["snapshot_date"] is None
    assert result["coverage"]["date_data_available"] is False
    assert len(calls)==8<=MAX_REQUESTS
    assert result["items"]==[]

@pytest.mark.parametrize("budget_stage",["draft","original","supplementary","settlement"])
def test_current_funds_cannot_establish_requested_adopted_or_draft_amount(setup,budget_stage):
    async def request(params): return envelope([row(params["exe_ymd"])])
    setup.setattr(F,"_request",request)
    result=call(budget_stage=budget_stage)
    assert result["status"]=="PARTIAL"
    assert result["budget_basis"]["requested_stage_verified"] is False
    assert result["budget_basis"]["returned_stage"]=="current"
    assert result["items"][0]["amount_unit"]=="SOURCE_CONFIRMATION_REQUIRED"

@pytest.mark.parametrize("snapshot_date",["2027-01-01","2025-12-31","2026-02-30","2026-10-02","bad"])
def test_invalid_date_fails_before_network(setup,snapshot_date):
    async def request(params): pytest.fail("invalid date must not query API")
    setup.setattr(F,"_request",request)
    assert call(snapshot_date=snapshot_date)["status"]=="INVALID_INPUT"

def test_explicit_date_excludes_wrong_date_and_neighbor_government(setup):
    async def request(params):
        return envelope([row(),row("20260929"),row(laf_hg_nm="부산광역시 서구",laf_cd="2614000")])
    setup.setattr(F,"_request",request)
    result=call(snapshot_date="2026-09-30")
    assert len(result["items"])==1
    assert result["date_resolution"]["mixed_dates"] is False

def test_missing_expenditure_stays_unknown(setup):
    async def request(params): return envelope([row(params["exe_ymd"],ep_amt=None)])
    setup.setattr(F,"_request",request)
    item=call()["items"][0]
    assert item["expenditure"] is None
    assert item["execution_rate_percent"] is None
    assert item["unspent_current_amount"] is None

def test_nonlocal_capped_page_is_partial_not_empty(setup):
    async def request(params):
        return envelope([row(params["exe_ymd"],laf_hg_nm="부산광역시 서구")],2000)
    setup.setattr(F,"_request",request)
    result=call("빈집")
    assert result["status"]=="PARTIAL"
    assert result["coverage"]["has_unread_pages"] is True
    assert result["items"]==[]

def test_brand_expansion_is_not_identity_certification(setup):
    async def request(params):
        return envelope([row(params["exe_ymd"])]) if params.get("dbiz_nm") in (None,"세상에서") else envelope()
    setup.setattr(F,"_request",request)
    item=call("세큰대")["items"][0]
    assert item["match_status"]=="RELATED_PROJECT_CANDIDATE"
    assert item["same_project_verified"] is False

def test_standalone_context_uses_same_snapshot_and_budget_rules(setup):
    async def request(params): return envelope([row(params["exe_ymd"])])
    setup.setattr(F,"_request",request)
    result=asyncio.run(F.context("세큰대","광주 서구",2026,budget_stage="draft"))
    assert result["status"]=="PARTIAL"
    assert result["budget_basis"]["returned_stage"]=="current"

@pytest.mark.parametrize("source,target",[
    ("전남광주서구","전남광주통합특별시 서구의회"),
    ("서울용산구","서울특별시 용산구의회"),
    ("부산서구","부산광역시 서구의회"),
    ("경기광주시","경기도 광주시의회"),
    ("서울본청","서울특별시의회"),
])
def test_province_abbreviations_preserve_full_government_identity(source,target):
    assert V.finance_belongs({"laf_hg_nm":source},target)

@pytest.mark.parametrize("source",["서구","부산서구","대전서구","인천서구"])
def test_ambiguous_and_other_seogu_never_match_gwangju(source):
    assert not V.finance_belongs({"laf_hg_nm":source},"광주 서구")
