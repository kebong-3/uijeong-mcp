# -*- coding: utf-8 -*-
"""실제 규모 회의록에서 MCP 경계 전송량이 한도 안에 있는지 확인한다.

관측 근거: 실제 CLIK 회의록 한 건이 발언 879개 규모였다(v1.2 보고서 T06). 이 규모
세 건으로 council_prepare_pack을 호출하면 보완 전 3,271,918자(약 160만 토큰)가
반환되어 어떤 클라이언트에서도 사용할 수 없었다. 아래 시험은 그 조건을 고정한다.
본문은 형식·규모만 모사한 합성자료이며 실제 발언이 아니다.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import response_budget as B
import uijeong_mcp as U

TURNS = 879
LONG_BODY = "".join(
    f"<b>○{'김가상 위원' if i % 3 == 0 else ('기획과장 이가상' if i % 3 == 1 else '위원장 최가상')}</b> "
    f"발언 {i}번입니다. 성인지예산 관련하여 확인드립니다. "
    + ("상세 설명을 덧붙입니다. " * 20) + "<br>"
    for i in range(TURNS))


def _meta(docid, date="20250101"):
    return dict(DOCID=docid, MINTS_HTML=LONG_BODY, RASMBLY_ID="062006", RASMBLY_NM="가상서구의회",
                RASMBLY_NUMPR="10", RASMBLY_SESN="340", MINTS_ODR="1",
                MTGNM="기획총무위원회", MTG_DE=date)


@pytest.fixture
def heavy(monkeypatch, tmp_path):
    U.clik._cache.clear()
    monkeypatch.setattr(U, "API_KEY", "TEST-ONLY")
    from runtime_security import SQLiteBudget, SnapshotStore
    monkeypatch.setattr(U.clik, "_budget", SQLiteBudget(tmp_path / "budget.db", 1000))
    rows = [_meta(f"D{i}", f"2025010{i + 1}") for i in range(3)]

    async def raw(path, params):
        if params.get("displayType") == "detail":
            return [{"RESULT_CODE": "SUCCESS", **next(r for r in rows if r["DOCID"] == params["docid"])}]
        start = params.get("startCount", 0)
        return [{"RESULT_CODE": "SUCCESS", "TOTAL_COUNT": len(rows),
                 "LIST": [{"ROW": r} for r in rows[start:start + 100]]}]
    monkeypatch.setattr(U.clik, "_raw_get", raw)
    return rows


def _wire(name, args):
    result = asyncio.run(U.mcp.call_tool(name, args))
    text = result.content[0].text if result.content else ""
    structured = result.structuredContent or {}
    return text, structured, len(text) + B.size_of(structured)


def test_prepare_pack_fits_the_budget_on_a_real_sized_record(heavy):
    text, structured, total = _wire("council_prepare_pack",
                                    {"keyword": "성인지예산", "council": "광주 서구",
                                     "source": "clik", "max_docs": 3}
                                    if False else
                                    {"keyword": "성인지예산", "council": "광주 서구", "max_docs": 3})
    assert B.size_of(structured) <= B.max_chars(), "구조화 결과가 응답 한도를 넘으면 클라이언트가 쓸 수 없다"
    assert total < 60_000, f"전송 총량 {total:,}자: 한 호출이 컨텍스트를 삼키지 않아야 한다"
    assert structured["status"] == "PARTIAL"
    assert structured["response_budget"]["truncated"] is True
    assert structured["response_budget"]["original_chars"] > B.max_chars()


def test_prepare_pack_sections_are_not_duplicated(heavy):
    _, pack, _ = _wire("council_prepare_pack",
                       {"keyword": "성인지예산", "council": "광주 서구", "max_docs": 3})
    brief = pack["briefing"]
    assert brief["followup_candidates"] is None and brief["preparation_questions"] is None
    assert brief["followup_candidates_ref"] == "followup_ledger.entries"
    assert brief["preparation_questions_ref"] == "question_candidates.candidates"
    ledger = json.dumps(pack["followup_ledger"]["entries"], ensure_ascii=False, sort_keys=True)
    inside = json.dumps(brief.get("followup_candidates"), ensure_ascii=False, sort_keys=True)
    assert ledger != inside, "같은 본문을 두 절에서 반복하면 응답이 두 배가 된다"


def test_prepare_pack_states_how_much_evidence_was_held_back(heavy):
    _, pack, _ = _wire("council_prepare_pack",
                       {"keyword": "성인지예산", "council": "광주 서구", "max_docs": 3,
                        "max_evidence": 5})
    totals = pack["briefing"]["evidence_totals"]
    assert totals["discussion_evidence_shown"] <= 5
    assert totals["discussion_evidence_total"] >= totals["discussion_evidence_shown"]
    assert "item_offset" in totals["retrieval"]


def test_evidence_bundle_fits_the_budget(heavy):
    _, bundle, total = _wire("council_evidence_bundle",
                             {"keyword": "성인지예산", "council": "광주 서구",
                              "source": "clik", "max_docs": 3, "limit": 30})
    assert B.size_of(bundle) <= B.max_chars()
    assert total < 60_000
    assert bundle["snapshot_id"], "축약해도 이어보기 식별자는 남아야 한다"


def test_read_source_paginates_instead_of_dumping(heavy):
    _, page, total = _wire("council_read_source", {"ref": "D0"})
    assert total < 40_000
    assert page["status"] in ("PARTIAL", "COMPLETE")
    nxt = page.get("next_start_turn")
    assert nxt, "879개 발언을 한 번에 반환하지 않고 이어읽기 위치를 준다"
    _, page2, _ = _wire("council_read_source", {"ref": "D0", "start_turn": nxt})
    assert page2["status"] in ("PARTIAL", "COMPLETE")


def test_invalid_max_evidence_is_input_error(heavy):
    _, out, _ = _wire("council_prepare_pack",
                      {"keyword": "성인지예산", "council": "광주 서구", "max_evidence": 0})
    assert out["status"] == "INVALID_INPUT"
