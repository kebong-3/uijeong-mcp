import json
from pathlib import Path

import pytest

import sources


def test_registry_has_authority_and_separates_coverage():
    data = sources.load_sources()
    assert data["directory_host_count"] == 243
    assert len(data["sources"]) == data["source_count"] == 248
    assert len({r["source_id"] for r in data["sources"]}) == 248
    assert sum(bool(r["direct_adapter"]) for r in data["sources"]) == 1
    assert all(r["clik_coverage"] == "must_check_per_query" for r in data["sources"])
    assert all(r["directory_url"] for r in data["sources"] if r["official_host"])


def test_official_code_snapshot_includes_new_and_historical_codes():
    current = sources.council_code_map(False)
    all_codes = sources.council_code_map()
    assert len(current) == 243 and len(all_codes) == 245
    assert current["065001"] == "전남광주통합특별시의회"
    assert current["032015"] == "인천광역시 검단구의회"
    assert all_codes["062001"] == "광주광역시의회"
    assert all_codes["061001"] == "전라남도의회"
    assert "062001" not in current


@pytest.mark.parametrize("query,expected", [
    ("광주 서구", "062006"), ("광주광역시 서구의회", "062006"),
    ("전남광주통합특별시 서구의회", "062006"), ("경기 광주시", "031006"),
    ("광주시의회", "031006"), ("광주광역시의회", "062001"),
    ("전라남도의회(통합 전)", "061001"), ("전남광주통합특별시의회", "065001"),
    ("서울 광진구", "002007"), ("062006", "062006"),
])
def test_resolver_keeps_distinct_histories(query, expected):
    assert [r["council_id"] for r in sources.resolve_councils(query)] == [expected]


def test_unknown_id_and_ambiguous_name_never_guessed():
    assert sources.resolve_councils("999999") == []
    assert len(sources.resolve_councils("서구")) > 1
    assert len(sources.resolve_councils("광주")) > 1


def test_legacy_incheon_sites_not_assigned_new_codes():
    rows = sources.load_sources()["sources"]
    legacy = [r for r in rows if r["directory_name"] in ("인천광역시 동구의회", "인천광역시 중구의회", "인천광역시 서구의회")]
    assert len(legacy) == 3
    assert all(r["council_id"] is None for r in legacy)


def test_source_pagination_and_direct_filter():
    all_rows = []
    offset = 0
    while True:
        result = sources.search_sources(offset=offset, limit=37)
        all_rows.extend(r["source_id"] for r in result["sources"])
        if result["next_offset"] is None:
            break
        offset = result["next_offset"]
    assert len(all_rows) == len(set(all_rows)) == 248
    direct = sources.search_sources(direct_only=True)
    assert direct["total_matches"] == 1
    assert direct["sources"][0]["council_id"] == "062006"
    assert sources.search_sources("전남광주통합특별시의회")["total_matches"] == 1


@pytest.mark.parametrize("url", [
    "http://www.gjsc.or.kr/record", "https://www.gjsc.or.kr.evil.test/record",
    "https://evil.test@www.gjsc.or.kr/record", "https://www.gjsc.or.kr:444/record",
    "https://127.0.0.1/record", "https://www.gjsc.or.kr\\@evil.test/record",
    "javascript:alert(1)", "https://www.gjsc.or.kr/record?api_key=secret",
    "https://clik.nanet.go.kr/openapi/minutes.do?key=secret",
])
def test_unsafe_reference_urls_rejected(url):
    with pytest.raises(ValueError):
        sources.validate_official_source_url(url)


def test_record_key_is_not_confused_with_api_key():
    url = "https://www.gjsc.or.kr/kr/assembly/recordView.do?key=public-document-id"
    assert sources.validate_official_source_url(url) == url


def test_link_discovery_rejects_cross_host_and_does_not_upgrade_source():
    html = '''<base href="https://evil.test/"><a href="/kr/assembly/late.do">최근회의록</a>
        <a href="javascript:alert(1)">회의록</a><a href="https://evil.test/minutes">회의록</a>
        <a href="https://council.gwangjin.go.kr/minutes">회의록</a>
        <a href="/kr/assembly/late.do">회의록 중복</a><a href="#minutes">회의록</a>
        <a href="/kr/assembly/speech.do">5 분 자유발언</a><a href="/login">로그인</a>'''
    result = sources.discover_minutes_links(html, "https://www.gjsc.or.kr/kr/main.do")
    assert result["source_kind"] == "USER_PROVIDED"
    assert result["total_candidates"] == 2
    assert all(not r["fetched"] for r in result["links"])
    assert all(r["url"].startswith("https://www.gjsc.or.kr/") for r in result["links"])


def test_link_discovery_truncation_is_explicit():
    result = sources.discover_minutes_links(''.join(f'<a href="/x{i}">회의록</a>' for i in range(5)),
                                            "https://www.gjsc.or.kr/", limit=2)
    assert result["total_candidates"] == 5 and len(result["links"]) == 2
    assert result["truncated"]


@pytest.mark.parametrize("kwargs", [{"limit":0}, {"limit":101}, {"limit":True}, {"offset":-1}, {"offset":True}])
def test_invalid_source_paging(kwargs):
    with pytest.raises(ValueError):
        sources.search_sources(**kwargs)


def test_actual_official_text_excerpts_preserve_speakers_without_claiming_html_qa():
    import evidence_core as evidence
    data = json.loads((Path(__file__).parent / "fixtures" / "official_excerpts.json").read_text(encoding="utf-8"))
    for item in data["excerpts"]:
        assert item["source_format"] == "web-rendered excerpt, not original HTML"
        turns = evidence.parse_turns(item["text"])
        assert [t["label"] for t in turns] == item["expected_labels"]
        assert [t["role"] for t in turns] == item["expected_roles"]
        assert all(t["text"] in item["text"] for t in turns)
    procedural = evidence.parse_turns(data["excerpts"][0]["text"])
    assert evidence.build_qa_pairs(procedural) == []
