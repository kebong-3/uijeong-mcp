"""Offline tests for v2.7 legislation/member/finance context extensions."""
import asyncio

import council_extensions as C
import finance_context as F
import legal_context as L


def test_law_missing_credential_is_not_empty(monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    result = asyncio.run(L.context("고독사", "전남광주통합특별시 서구"))
    assert result["status"] == "NOT_CONFIGURED"
    assert result["configuration"]["env"] == "LAW_OC"
    assert result["laws"] == [] and result["ordinances"] == []


def test_law_listing_normalization_and_public_urls():
    payload = {
        "LawSearch": {
            "totalCnt": "1",
            "law": [{
                "법령ID": "1234",
                "법령일련번호": "5678",
                "법령명한글": "고독사 예방 및 관리에 관한 법률",
                "공포일자": "20260101",
                "법령구분명": "법률",
            }],
        }
    }
    rows = L._listing_rows(payload, "law")
    assert len(rows) == 1
    assert rows[0]["title"] == "고독사 예방 및 관리에 관한 법률"
    assert rows[0]["source_url"].startswith("https://www.law.go.kr/")
    assert "OC=" not in rows[0]["source_url"]


def test_ordinance_jurisdiction_alias_accepts_historical_name():
    rows = [{
        "kind":"ordinance","document_id":"1","mst":"2","title":"광주광역시 서구 고독사 예방 조례",
        "jurisdiction":"광주광역시 서구","source_url":"https://www.law.go.kr/ordinInfoP.do?ordinSeq=2",
    }]
    matched, ok = L._filter_jurisdiction(rows, "전남광주통합특별시 서구")
    assert ok and matched == rows


def test_finance_slots_are_explicit(monkeypatch):
    monkeypatch.delenv("FINANCE365_SERVICE_KEY", raising=False)
    monkeypatch.delenv("FINANCE365_API_URL", raising=False)
    cfg = F.configuration()
    assert cfg["configured"] is False
    assert cfg["env"]["service_key"] == "FINANCE365_SERVICE_KEY"
    assert cfg["env"]["api_url"] == "FINANCE365_API_URL"
    result = asyncio.run(F.context("체납관리단", "전남광주통합특별시 서구의회"))
    assert result["status"] == "NOT_CONFIGURED"
    assert result["items"] == []


def test_admin_term_expansion_is_bounded():
    values = C._expansions("체납관리단 운영 문제", 2)
    assert len(values) <= 2
    assert values
    assert len(set(values)) == len(values)


class FakeClik:
    async def get(self, endpoint, **params):
        assert endpoint == "assemblyinfo.do"
        assert params["searchType"] in {"SPKNG_CN","BI_SJ"}
        return {"TOTAL_COUNT":"1","rows":[{
            "DOCID":"M1",
            "ASEMBY_NM":"홍길동",
            "RASMBLY_NM":"전남광주통합특별시 서구의회",
            "PPRTY_NM":"테스트정당",
        }]}


class FakeMemberBackend:
    clik = FakeClik()
    @staticmethod
    def _rows(obj):
        return obj["rows"]


def test_member_discovery_is_metadata_only():
    result = asyncio.run(C._member_discovery(FakeMemberBackend(), "체납관리단", "062006", 6))
    assert result["status"] == "COMPLETE"
    assert result["items"][0]["role"] == "DISCOVERY_ONLY"
    assert "party" not in result["items"][0]
    assert result["interpretation"].startswith("의원정보는")


class FakeInstallBackend:
    RO = object()
    class M:
        def remove_tool(self, name):
            pass
        def tool(self, **kwargs):
            return lambda fn: fn
    mcp = M()
    @staticmethod
    def profile_allows(name):
        return False


def test_extension_install_attaches_three_public_functions():
    U = FakeInstallBackend()
    C.install(U)
    assert callable(U.council_legislation_context)
    assert callable(U.council_finance_context)
    assert callable(U.council_context_pack)
