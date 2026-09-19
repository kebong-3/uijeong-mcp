"""Contract tests against source attribution and administrative overstatement."""
import copy
import hashlib
import json

import pytest

from workflow_core import build_briefing, build_faq_candidates, build_followup_ledger


def event(record="r1", question="예산 집행이 낮은 이유는 무엇입니까?", answer="예산이 확보되면 다음 회기까지 자료를 제출하겠습니다.", source_kind="SYNTHETIC"):
    def turn(index, text, role, label):
        return {"turn_index": index, "text": text, "role": role, "label": label, "agenda": 2,
                "act": "question" if role == "member" else "answer",
                "citation": {"record_id": record, "docid": "doc-" + record, "turn_index": index,
                             "source_url": "https://example.gov.test/minutes/" + record,
                             "source_kind": source_kind, "locator": "parsed_turn", "fiscal_year": None}}
    return {"event_id": record + "-q1", "kind": "qa", "record_id": record, "docid": "doc-" + record,
            "metadata": {"council": "시험의회", "meeting_date": "2026-09-17", "committee": "시험위원회"},
            "source_kind": source_kind, "provenance": {"test_fixture": True},
            "question": turn(3, question, "member", "시험위원 가"),
            "answers": [turn(4, answer, "official", "시험과장 나")] if answer is not None else [],
            "speech": None, "commitment": None}


def test_briefing_preserves_exact_quote_and_locator():
    raw = "  이 사업은  실패 아닙니까?\n다시 설명하십시오. "
    original = event(question=raw)
    result = build_briefing([original], topic="사업예산", coverage={"status": "PARTIAL", "checked": 3})
    quote = result["discussion_evidence"][0]["question"]
    assert quote["text"] == raw
    assert quote["quote_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert quote["citation"]["record_id"] == "r1"
    assert quote["citation"]["turn_index"] == 3
    assert quote["citation"]["source_url"] == original["question"]["citation"]["source_url"]
    assert result["coverage"] == {"status": "PARTIAL", "checked": 3}
    assert result["status"] == "PARTIAL"


def test_synthetic_evidence_cannot_be_upgraded_by_citation():
    sample = event()
    sample["question"]["citation"]["source_kind"] = "OFFICIAL"
    result = build_briefing([sample], topic="예산")
    question = result["discussion_evidence"][0]["question"]
    assert question["source_kind"] == "SYNTHETIC"
    assert question["citation"]["source_kind"] == "SYNTHETIC"
    assert question["source_label"] == "합성 시험자료"


def test_synthetic_citation_cannot_be_upgraded_by_event():
    sample = event()
    sample["source_kind"] = "OFFICIAL"
    assert build_briefing([sample], topic="예산")["discussion_evidence"][0]["question"]["source_kind"] == "SYNTHETIC"


def test_user_evidence_cannot_be_upgraded_by_nested_official_citation():
    sample = event(source_kind="USER_PROVIDED")
    sample["question"]["citation"]["source_kind"] = "PUBLIC_API"
    assert build_briefing([sample], topic="예산")["discussion_evidence"][0]["question"]["source_kind"] == "USER_PROVIDED"


def test_fiscal_year_never_inferred_from_meeting_date():
    result = build_briefing([event()], topic="결산")
    assert result["discussion_evidence"][0]["metadata"]["fiscal_year"] is None
    assert result["discussion_evidence"][0]["question"]["citation"]["fiscal_year"] is None


def test_missing_answer_remains_unlinked_not_no_answer():
    row = build_faq_candidates([event(answer=None)], topic="예산")["candidates"][0]
    assert row["question_occurrences"][0]["answer_link_status"] == "NOT_LINKED_IN_SCOPE"
    assert row["current_answer"] is None
    assert row["current_answer_status"] == "CURRENT_SUPPORTING_DOCUMENTS_REQUIRED"


def test_no_question_is_generated_from_department_report():
    sample = event()
    sample["speech"] = sample["answers"][0]
    sample["speech"]["act"] = "report"
    sample["question"] = None
    sample["answers"] = []
    result = build_faq_candidates([sample], topic="예산")
    assert result["candidates"] == []
    assert result["status"] == "PARTIAL"
    assert len(build_briefing([sample], topic="예산")["other_speech_evidence"]) == 1


def test_frequency_is_per_record_and_normalizes_only_whitespace():
    first = event()
    duplicate_occurrence = copy.deepcopy(first)
    duplicate_occurrence["event_id"] = "r1-q2"
    duplicate_occurrence["question"]["citation"]["turn_index"] = 8
    second = event("r2", question="예산집행이 낮은 이유는 무엇입니까?")
    distinct = event("r3", question="예산 집행률 개선 방안은 무엇입니까?")
    result = build_faq_candidates([first, duplicate_occurrence, second, distinct], topic="예산")
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["occurrence_count_in_supplied_records"] == 2
    assert len(result["candidates"][0]["question_occurrences"]) == 3
    assert result["candidates"][1]["occurrence_count_in_supplied_records"] == 1
    assert result["supplied_document_count"] == 3
    assert result["candidates"][0]["supplied_document_count"] == 3


def test_unidentified_events_are_not_counted_as_identified_documents():
    sample = event()
    sample.pop("record_id")
    sample.pop("docid")
    result = build_faq_candidates([sample], topic="예산")
    assert result["supplied_document_count"] == 0
    assert result["candidates"][0]["occurrence_count_in_supplied_records"] == 0
    assert result["candidates"][0]["unidentified_source_occurrences"] == 1


def test_same_day_different_record_is_retained():
    result = build_briefing([event("r1"), event("r2")], topic="예산")
    assert len(result["discussion_evidence"]) == 2


def test_exact_event_duplicate_only_is_removed():
    first = event()
    changed = copy.deepcopy(first)
    changed["answers"][0]["text"] = "원문 정정 내용입니다."
    result = build_briefing([first, copy.deepcopy(first), changed], topic="예산")
    assert result["exact_duplicate_events_removed"] == 1
    assert len(result["discussion_evidence"]) == 2


def commitment_event():
    sample = event()
    sample["kind"] = "commitment"
    sample["commitment"] = {"type": "조건부 추진", "condition": "예산이 확보되면", "deadline": "다음 회기까지",
                            "excerpt": "예산이 확보되면 다음 회기까지 자료를 제출하겠습니다.", "status": "COMPLETED"}
    return sample


def test_followup_retains_exact_condition_deadline_but_never_completion():
    row = build_followup_ledger([commitment_event()])["entries"][0]
    assert row["condition_verbatim"] == "예산이 확보되면"
    assert row["deadline_verbatim"] == "다음 회기까지"
    assert row["calendar_due_date"] is None
    assert row["owner_department"] is None
    assert row["fulfillment_status"] == "EVIDENCE_NOT_VERIFIED"
    assert row["fulfillment_label"] == "후속 증빙 미확인"
    assert row["excerpt_status"] == "EXACT_SUBSTRING"
    assert row["candidate_citation"]["turn_index"] == 4


def test_fabricated_commitment_excerpt_and_due_date_are_not_quoted():
    sample = commitment_event()
    sample["commitment"].update(excerpt="이미 사업을 완료했습니다.", deadline="2026-10-31", condition="의회 승인 시")
    row = build_followup_ledger([sample])["entries"][0]
    assert row["candidate_excerpt"] is None
    assert row["excerpt_status"] == "SOURCE_SENTENCE_REVIEW_REQUIRED"
    assert row["condition_verbatim"] is None
    assert row["deadline_verbatim"] is None
    assert row["source_answers"][0]["text"] == sample["answers"][0]["text"]


def test_no_commitment_inferred_from_keyword_in_question():
    sample = event(question="지난번 약속한 예산 지원은 완료되었습니까?")
    assert build_followup_ledger([sample])["entries"] == []


def test_missing_citation_marked_incomplete():
    sample = event()
    sample.pop("record_id")
    sample.pop("docid")
    sample["question"].pop("citation")
    row = build_briefing([sample], topic="예산")["discussion_evidence"][0]
    assert row["question"]["locator_status"] == "LOCATOR_INCOMPLETE"
    assert row["question"]["citation"]["source_url"] is None


def test_prior_answer_is_not_current_answer():
    row = build_faq_candidates([event(answer="전체 사업비는 20억원입니다.")], topic="예산")["candidates"][0]
    assert row["current_answer"] is None
    assert row["question_occurrences"][0]["answers"][0]["fact_status"] == "STATEMENT_ONLY_CURRENT_FACT_NOT_VERIFIED"


def test_input_is_never_modified_or_aliased_by_output():
    sample = commitment_event()
    before = copy.deepcopy(sample)
    coverage = {"status": "PARTIAL", "years": [2024, 2025]}
    result = build_briefing([sample], topic="예산", coverage=coverage)
    result["coverage"]["years"].append(2026)
    result["discussion_evidence"][0]["provenance"]["test_fixture"] = False
    assert sample == before
    assert coverage["years"] == [2024, 2025]


def test_upstream_failure_is_not_empty_search_success():
    assert build_briefing([], topic="예산", coverage={"status": "ERROR"})["status"] == "ERROR"
    assert build_briefing([event()], topic="예산", coverage={"status": "ERROR"})["status"] == "PARTIAL"
    assert build_briefing([], topic="예산", coverage={"status": "OK"})["status"] == "EMPTY"


def test_no_personal_profile_fields_are_exported():
    sample = event()
    sample.update(personality="공격적", political_score=99, pressure_strategy="취약점 공략")
    serialized = json.dumps(build_briefing([sample], topic="예산"), ensure_ascii=False)
    assert "personality" not in serialized
    assert "political_score" not in serialized
    assert "pressure_strategy" not in serialized
    assert "취약점 공략" not in serialized


def test_faq_limit_reports_omission():
    result = build_faq_candidates([event("r1"), event("r2", question="어떻게 개선합니까?")], topic="예산", limit=1)
    assert result["truncated"] is True
    assert result["omitted_candidate_count"] == 1
    assert result["total_candidate_count"] == 2


@pytest.mark.parametrize("records", [None, {}, [None], [{"raw_text": "미분석 자료"}], [{"question": "문자열"}], [{"answers": "문자열"}]])
def test_malformed_evidence_rejected(records):
    with pytest.raises(ValueError):
        build_briefing(records, topic="예산")


@pytest.mark.parametrize("topic", ["", " " * 3, None, "가" * 301])
def test_invalid_topic_rejected(topic):
    with pytest.raises(ValueError):
        build_faq_candidates([], topic=topic)


@pytest.mark.parametrize("limit", [0, 51, True, 1.5])
def test_invalid_limit_rejected(limit):
    with pytest.raises(ValueError):
        build_faq_candidates([], topic="예산", limit=limit)


def test_real_evidence_core_contract():
    from evidence_core import make_record, parse_turns, record_events
    text = "○ 위원 가상인 예산 집행 현황은 어떻습니까?\n○ 시험과장 시험인 예산이 확보되면 다음 회기까지 자료를 제출하겠습니다."
    record = make_record({"DOCID": "synthetic-contract", "meeting_date": "2026-09-17"},
                         parse_turns(text), source="fixture", source_kind="SYNTHETIC")
    qa = record_events(record, keyword="예산", mode="질의답변")
    followups = record_events(record, keyword="예산", mode="약속")
    assert len(qa) == 1
    assert len(followups) == 1
    report = build_briefing(qa + followups, topic="예산")
    assert report["discussion_evidence"][0]["question"]["source_kind"] == "SYNTHETIC"
    entry = report["followup_candidates"][0]
    assert entry["excerpt_status"] == "EXACT_SUBSTRING"
    citation = entry["candidate_citation"]
    source = entry["source_answers"][0]["text"]
    assert source[citation["char_start"]:citation["char_end"]] == entry["candidate_excerpt"]
