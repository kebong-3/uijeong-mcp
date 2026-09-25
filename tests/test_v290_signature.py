"""Offline contract/self-tests for v2.9 evidence-complete workflows."""
import asyncio

import council_v29 as V
import finance_context as F


class FakeClik:
    def __init__(self):
        self.rows = [
            {"DOCID":"D1","RASMBLY_ID":"002022","RASMBLY_NM":"서울특별시 용산구의회",
             "MTG_DE":"20250920","MTGNM":"본회의","MINTS_ODR":"1"},
            {"DOCID":"D2","RASMBLY_ID":"054002","RASMBLY_NM":"경상북도 경산시의회",
             "MTG_DE":"20250810","MTGNM":"본회의","MINTS_ODR":"1"},
        ]

    async def get(self, endpoint, **params):
        assert endpoint == "minutes.do"
        if params.get("displayType") == "list":
            return {"TOTAL_COUNT":"2","LIST":[{"ROW":x} for x in self.rows]}
        docid = params["docid"]
        row = next(x for x in self.rows if x["DOCID"] == docid)
        body = (
            "<b>○김테스트 위원</b> 직원 휴게공간의 실제 이용실적과 운영현황을 설명해 주십시오.<br>"
            "<b>○행정지원과장 홍길동</b> 직원 휴게공간을 운영하고 있으며 이용현황을 계속 점검하고 있습니다."
        )
        return {**row, "MINTS_HTML":body, "ORGINL_FILE_URL":"https://example.go.kr/minutes/"+docid}


class FakePeerBackend:
    clik = FakeClik()
    _rows = staticmethod(lambda obj: [x.get("ROW", x) for x in obj.get("LIST", [])])

    @staticmethod
    async def minutes_detail(docid):
        return await FakePeerBackend.clik.get("minutes.do", displayType="detail", docid=docid)


def test_peer_cases_are_distinct_councils_and_not_ranked():
    result = asyncio.run(V._peer_cases(FakePeerBackend, "직원 휴게공간", years=5, case_count=2, max_details=4))
    assert result["status"] == "COMPLETE"
    assert len(result["cases"]) == 2
    assert len({x["council_name"] for x in result["cases"]}) == 2
    assert result["coverage_card"]["is_exhaustive_national_archive"] is False
    assert result["interpretation"][0].startswith("반환 순서는 우수성")


def test_peer_cases_empty_is_bounded_not_global_absence():
    class EmptyClik:
        async def get(self, endpoint, **params):
            return {"TOTAL_COUNT":"0","LIST":[]}
    class EmptyBackend:
        clik = EmptyClik()
        _rows = staticmethod(lambda obj: [])
    result = asyncio.run(V._peer_cases(EmptyBackend, "아주희귀한주제", years=2, case_count=3, max_details=3))
    assert result["status"] == "EMPTY"
    assert result["coverage_card"]["is_exhaustive_national_archive"] is False


def test_finance_progressive_widening_stops_after_first_match(monkeypatch):
    calls = []
    monkeypatch.setenv("LOFIN_API_KEY", "dummy")
    async def fake_request(params):
        calls.append(params["dbiz_nm"])
        if params["dbiz_nm"] == "휴라운지":
            return {"result_code":"INFO-200","message":"없음","total_count":0,"rows":[]}
        return {
            "result_code":"INFO-000","message":"정상","total_count":1,
            "rows":[{
                "fyr":"2026","exe_ymd":"20260926","laf_hg_nm":"광주서구","laf_cd":"X",
                "dbiz_cd":"B","dbiz_nm":"직원 후생복지","acnt_dv_nm":"일반회계",
                "bdg_cash_amt":"1000000","ep_amt":"500000","cpl_amt":"1000000",
            }]
        }
    monkeypatch.setattr(F, "_request", fake_request)
    result = asyncio.run(F.context("휴라운지","광주 서구",2026,20,search_terms=["직원 후생복지","직원복지"]))
    assert result["status"] == "COMPLETE"
    assert calls == ["휴라운지","직원 후생복지"]
    assert result["search_strategy"]["progressive_widening"] is True


class FakeDeptBackend:
    async def council_department_brief(self, **kwargs):
        return {"status":"COMPLETE","items":[{"kind":"질의답변"}],"errors":[]}
    async def council_recurring_issues(self, **kwargs):
        return {"status":"COMPLETE","recurring":[{"term":"이용실적","years":2}],"errors":[]}


def test_department_session_brief_is_not_prediction():
    result = asyncio.run(V._department_session_brief(
        FakeDeptBackend(), "행정지원과", council="광주 서구",
        purpose="행정사무감사", years=3
    ))
    assert result["status"] == "COMPLETE"
    assert result["coverage_card"]["is_prediction"] is False
    assert result["focus_topic_candidates"][0]["term"] == "이용실적"


def test_coverage_status_contract():
    assert V._coverage_status(errors=[], returned=3, requested=3) == "COMPLETE"
    assert V._coverage_status(errors=[], returned=1, requested=3) == "PARTIAL"
    assert V._coverage_status(errors=[], returned=0, requested=3) == "EMPTY"
    assert V._coverage_status(errors=[{"x":1}], returned=0, requested=3) == "ERROR"
