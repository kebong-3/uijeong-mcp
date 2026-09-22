# -*- coding: utf-8 -*-
"""최종본에서 보완한 운영 조건 시험: 스냅샷 축출·도구 프로필·MCP 경계 전송량.

공유 배포에서 관측한 문제를 고정한다. 합성 입력만 사용하며 외부 호출은 없다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import response_budget as B
import runtime_security as R


# ── 스냅샷 보관 압력 ───────────────────────────────────────────────────────
def test_default_store_refuses_rather_than_evicting(tmp_path):
    """기본값은 여전히 거절이다: 이어보기 중인 커서를 말없이 무효화하지 않는다."""
    store = R.SnapshotStore(tmp_path / "s.db", "t", max_entries=1)
    kept = store.put({"public": "x"})
    with pytest.raises(R.SecurityError):
        store.put({"public": "y"})
    assert store.get(kept) == {"public": "x"} and store.evicted == 0


def test_opt_in_eviction_drops_oldest_and_counts_it(tmp_path):
    store = R.SnapshotStore(tmp_path / "s.db", "t", max_entries=3, evict_oldest=True)
    ids = [store.put({"i": i}) for i in range(3)]
    fresh = store.put({"i": 99})
    assert store.evicted == 1, "축출 건수를 세지 않으면 응답에 알릴 수 없다"
    assert store.get(ids[0]) is None and store.get(ids[-1]) == {"i": 2}
    assert store.get(fresh) == {"i": 99}


def test_total_byte_cap_evicts_until_it_fits(tmp_path):
    store = R.SnapshotStore(tmp_path / "s.db", "t", max_entries=999,
                            evict_oldest=True, max_total_bytes=600)
    for i in range(15):
        store.put({"pad": "한" * 40, "i": i})
    assert store.evicted > 0
    with R._connect(tmp_path / "s.db") as conn:
        total = conn.execute("SELECT coalesce(sum(length(payload)),0) FROM snapshots").fetchone()[0]
    assert total <= 600


def test_scope_isolation_survives_eviction(tmp_path):
    path = tmp_path / "s.db"
    mine = R.SnapshotStore(path, "org-a", max_entries=1, evict_oldest=True)
    theirs = R.SnapshotStore(path, "org-b", max_entries=1, evict_oldest=True)
    other = theirs.put({"public": "b"})
    mine.put({"public": "a1"})
    mine.put({"public": "a2"})          # org-a 안에서만 축출
    assert theirs.get(other) == {"public": "b"}


@pytest.mark.parametrize("bad", [-1])
def test_invalid_total_byte_cap(tmp_path, bad):
    with pytest.raises(ValueError):
        R.SnapshotStore(tmp_path / "s.db", "t", max_total_bytes=bad)


# ── 도구 프로필 ────────────────────────────────────────────────────────────
def _tools(profile, monkeypatch):
    monkeypatch.setenv("UIJEONG_PROFILE", profile)
    monkeypatch.setenv("CLIK_API_KEY", "TEST")
    for name in ("uijeong_mcp", "service_v2", "result_contract", "response_budget"):
        sys.modules.pop(name, None)
    import asyncio
    import uijeong_mcp as U
    return {t.name for t in asyncio.run(U.mcp.list_tools())}, U


def test_core_profile_exposes_five_entry_tools(monkeypatch):
    names, U = _tools("core", monkeypatch)
    assert names == U.CORE_TOOLS
    assert len(names) == 5


def test_profiles_are_nested(monkeypatch):
    core, _ = _tools("core", monkeypatch)
    lite, _ = _tools("lite", monkeypatch)
    full, _ = _tools("full", monkeypatch)
    assert core < lite < full, "좁은 프로필의 도구는 넓은 프로필에도 있어야 한다"
    assert len(lite) == 22 and len(full) == 34


def test_unknown_profile_falls_back_to_full(monkeypatch):
    names, _ = _tools("존재하지않는프로필", monkeypatch)
    assert len(names) == 34


# ── MCP 경계: 전송량과 오류 표시 ───────────────────────────────────────────
@pytest.mark.parametrize("status,is_error", [("COMPLETE", False), ("PARTIAL", False),
                                             ("EMPTY", False), ("ERROR", True),
                                             ("INVALID_INPUT", True)])
def test_wire_marks_failures_and_keeps_structured(status, is_error):
    import asyncio

    import result_contract as C

    async def tool():
        return {"status": status, "items": []}
    result = asyncio.run(C.wire_result(tool)())
    assert result.isError is is_error
    assert result.structuredContent["status"] == status


def test_small_result_repeats_json_for_older_clients():
    import asyncio

    import result_contract as C

    async def tool():
        return {"status": "COMPLETE", "items": [{"a": 1}]}
    result = asyncio.run(C.wire_result(tool)())
    assert json.loads(result.content[0].text)["items"] == [{"a": 1}]


def test_large_result_sends_digest_not_a_second_copy():
    import asyncio

    import result_contract as C

    def rows(prefix, count):
        return [{"record_id": f"{prefix}{i}", "source_kind": "PUBLIC_CLIK",
                 "question": {"text": "합성 발언입니다. " * 60, "turn_index": i}} for i in range(count)]

    big = {"status": "COMPLETE", "topic": "합성주제",
           "coverage": [{"source": "CLIK", "scanned": 300, "parsed": 20}],
           "items": rows("a", 200),
           "briefing": {"discussion_evidence": rows("b", 200), "other_speech_evidence": rows("c", 200)},
           "followup_ledger": {"entries": rows("d", 200)},
           "question_candidates": {"candidates": rows("e", 200)}}

    async def tool():
        return big
    result = asyncio.run(C.wire_result(tool)())
    text, structured = result.content[0].text, result.structuredContent
    assert B.size_of(structured) > B.text_json_max_chars(), "이 시험은 축약 후에도 큰 결과여야 한다"
    assert len(text) < B.size_of(structured) / 4, "텍스트가 구조화 결과를 그대로 복제하면 전송량이 두 배가 된다"
    assert "상태:" in text and "structuredContent" in text
    assert B.size_of(structured) <= B.max_chars()


def test_long_text_result_is_capped():
    import asyncio

    import result_contract as C

    async def tool():
        return "상태: PARTIAL\n" + "가" * 300_000
    text = asyncio.run(C.wire_result(tool)())
    assert isinstance(text, str) and len(text) <= B.max_chars() + 200
    assert "응답 한도" in text
