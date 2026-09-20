# -*- coding: utf-8 -*-
"""응답 예산 계층 시험.

도구 결과는 모델 컨텍스트 안에서 소비된다. 한도를 넘는 결과는 '더 완전한' 것이
아니라 쓰지 못하는 결과이므로, 축약하되 무엇을 줄였는지와 회수 경로를 남겨야 한다.
아래 자료는 형식 점검용 합성 입력이며 실제 발언·수치가 아니다.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import response_budget as B
import workflow_core as W


def _event(index: int, text_len: int = 400) -> dict:
    body = f"합성 질의 {index}번입니다. " + ("확인 요청 문장을 덧붙입니다. " * (text_len // 15))
    return {
        "event_id": f"e{index:04d}", "record_id": f"r{index:04d}", "kind": "qa",
        "source_kind": "PUBLIC_CLIK",
        "metadata": {"meeting_date": "2025-06-19", "council_name": "합성시의회",
                     "meeting_name": "합성위원회", "fiscal_year": None},
        "question": {"speaker": "합성 위원", "text": body, "turn_index": index,
                     "char_start": 0, "char_end": len(body), "quote_sha256": f"{index:064x}"},
        "answers": [{"speaker": "합성과장", "text": body, "turn_index": index + 1,
                     "char_start": 0, "char_end": len(body), "quote_sha256": f"{index:064x}"}],
    }


def test_short_payload_keeps_content_and_reports_budget():
    payload = {"status": "COMPLETE", "items": [{"a": 1}]}
    out = B.apply_budget(payload)
    assert out["items"] == [{"a": 1}]
    assert out["status"] == "COMPLETE"
    assert out["response_budget"]["truncated"] is False


def test_large_payload_fits_budget_and_names_omissions():
    payload = {"status": "COMPLETE", "items": [_event(i) for i in range(400)]}
    out = B.apply_budget(payload, limit=20_000)
    assert B.size_of(out) <= 20_000
    assert len(out["items"]) < 400
    omitted = out["items_omitted"]
    assert omitted["total"] == 400 and omitted["count"] == 400 - len(out["items"])
    assert "item_offset" in omitted["retrieval"]
    assert out["response_budget"]["truncated"] is True
    assert out["response_budget"]["reduced"], "축약 내역이 비어 있으면 무성 삭제와 같다"


def test_truncation_downgrades_complete_to_partial():
    out = B.apply_budget({"status": "COMPLETE", "items": [_event(i) for i in range(300)]}, limit=15_000)
    assert out["status"] == "PARTIAL"
    assert "COMPLETE" in out["response_budget"]["status_downgraded"]


def test_identifiers_and_offsets_survive_truncation():
    out = B.apply_budget({"status": "PARTIAL", "snapshot_id": "a" * 64, "next_item_offset": 10,
                          "items": [_event(i) for i in range(200)]}, limit=12_000)
    assert out["snapshot_id"] == "a" * 64 and out["next_item_offset"] == 10
    first = out["items"][0]
    for key in ("record_id", "event_id", "source_kind"):
        assert first[key], f"{key}는 축약 대상이 아니다"
    quote = first["question"]
    assert quote["turn_index"] == 0 and quote["quote_sha256"]
    assert quote["char_start"] == 0 and isinstance(quote["char_end"], int)


def test_long_quote_is_trimmed_not_reworded():
    original = "합성 발언입니다. " * 400
    out = B.apply_budget({"status": "COMPLETE", "items": [
        {"record_id": "r1", "question": {"text": original, "turn_index": 1}}]}, limit=3_000)
    kept = out["items"][0]["question"]["text"]
    assert kept.endswith("…") and original.startswith(kept[:-1]), "문구를 고치지 않고 앞에서 잘라야 한다"
    note = out["items"][0]["question"]["text_truncated"]
    assert note["original_chars"] == len(original) and note["kept_chars"] < len(original)


def test_hard_cap_is_a_guarantee_not_best_effort():
    """가장 작은 한도에서도 크기를 보장하고 식별자는 남긴다."""
    payload = {"status": "COMPLETE", "snapshot_id": "c" * 64, "keyword": "합성주제",
               "items": [_event(i, 2_000) for i in range(300)],
               "briefing": {"discussion_evidence": [_event(i, 2_000) for i in range(300)]}}
    out = B.apply_budget(payload, limit=B.MIN_MAX_CHARS)
    assert B.size_of(out) <= B.MIN_MAX_CHARS
    assert out["snapshot_id"] == "c" * 64 and out["keyword"] == "합성주제"
    assert out["status"] == "PARTIAL"
    assert out["response_budget"]["reduced"], "무엇을 줄였는지 남겨야 한다"


def test_minimal_fallback_keeps_identifiers_and_route():
    """모든 축약으로도 부족할 때의 마지막 방어선."""
    log = []
    out = B._minimal({"status": "COMPLETE", "snapshot_id": "d" * 64, "keyword": "합성주제",
                      "items": [{"x": 1}], "briefing": {"a": 1}}, 8_000, log)
    assert out["snapshot_id"] == "d" * 64 and out["items"] == []
    assert out["status"] == "PARTIAL" and "briefing" not in out
    assert "council_read_source" in out["budget_fallback"]["retrieval"]
    assert log and log[0]["kind"] == "envelope_reduced"


@pytest.mark.parametrize("cap", [8_000, 12_000, 20_000, 30_000, 45_000])
def test_cap_is_respected_across_sizes(cap):
    payload = {"status": "COMPLETE", "items": [_event(i, 900) for i in range(500)],
               "followup_ledger": {"entries": [_event(i, 900) for i in range(300)]}}
    assert B.size_of(B.apply_budget(payload, limit=cap)) <= cap


def test_empty_status_is_not_downgraded():
    out = B.apply_budget({"status": "EMPTY", "items": []})
    assert out["status"] == "EMPTY" and out["response_budget"]["truncated"] is False


def test_budget_env_override(monkeypatch):
    monkeypatch.setenv("UIJEONG_MAX_RESPONSE_CHARS", "9000")
    assert B.max_chars() == 9_000
    monkeypatch.setenv("UIJEONG_MAX_RESPONSE_CHARS", "10")
    assert B.max_chars() == B.MIN_MAX_CHARS
    monkeypatch.setenv("UIJEONG_MAX_RESPONSE_CHARS", "99999999")
    assert B.max_chars() == B.HARD_MAX_CHARS
    monkeypatch.setenv("UIJEONG_MAX_RESPONSE_CHARS", "숫자아님")
    assert B.max_chars() == B.DEFAULT_MAX_CHARS


def test_digest_states_status_scope_and_limits():
    payload = B.apply_budget({
        "status": "PARTIAL", "topic": "합성주제", "snapshot_id": "b" * 64,
        "coverage": [{"source": "CLIK", "scanned": 120, "selected": 6, "parsed": 6,
                      "upstream_total": 538, "next_offset": 100}],
        "items": [_event(i) for i in range(30)], "next_item_offset": 10,
        "limitations": ["확인 범위의 결과입니다."]}, limit=20_000)
    text = B.digest(payload)
    assert "상태: PARTIAL" in text and "b" * 64 in text
    assert "CLIK" in text and "538" in text
    assert "next_item_offset=10" in text
    assert "확인 범위의 결과입니다." in text
    assert len(text) <= B._DIGEST_MAX + 1


def test_digest_marks_empty_as_scope_limited():
    assert "전체 부재 아님" in B.digest({"status": "EMPTY", "items": []})


def test_error_digest_forbids_absence_reading():
    assert "자료 부재로 해석 금지" in B.digest({"status": "ERROR", "message": "상류 오류"})


# ── prepare_pack 절 중복 제거 ──────────────────────────────────────────────
def test_briefing_caps_evidence_and_reports_total():
    events = [_event(i) for i in range(120)]
    brief = W.build_briefing(events, topic="합성주제", max_evidence=10)
    assert len(brief["discussion_evidence"]) == 10
    totals = brief["evidence_totals"]
    assert totals["discussion_evidence_total"] == 120
    assert totals["discussion_evidence_shown"] == 10
    assert "item_offset" in totals["retrieval"]


def test_briefing_can_omit_derived_sections():
    events = [_event(i) for i in range(5)]
    with_derived = W.build_briefing(events, topic="합성주제")
    without = W.build_briefing(events, topic="합성주제", include_derived=False)
    assert with_derived["preparation_questions"] is not None
    assert without["preparation_questions"] is None and without["followup_candidates"] is None
    assert B.size_of(without) < B.size_of(with_derived)


@pytest.mark.parametrize("bad", [0, 201, -1, True, "10", None])
def test_briefing_rejects_bad_evidence_cap(bad):
    with pytest.raises(ValueError):
        W.build_briefing([_event(0)], topic="합성주제", max_evidence=bad)
