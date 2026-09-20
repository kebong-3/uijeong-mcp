"""Counterexamples for evidence integrity. Every name and speech is synthetic."""
import base64
import copy
import json
import sys
import unicodedata
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence_core as E

MIXED = """<script>○기획과장 악성인: 조작된 발언입니다.</script>
<b>○위원장 최가상</b> 의석을 정돈해 주십시오. 개의하겠습니다.<br>
○김가상 위원: 성인지 예산 지표를 어떻게 개선하겠습니까?<br>
<strong>○기획과장 이가상</strong>: 관련 지표는 10월 5일까지 수정하도록 하겠습니다.<br>
○박가상 위원: 언제요?
"""
META = {"DOCID": "D1", "RASMBLY_ID": "SYNTHETIC_COUNCIL", "RASMBLY_NM": "가상시의회", "RASMBLY_NUMPR": "9",
        "RASMBLY_SESN": "270", "MINTS_ODR": "1", "MTG_DE": "20250917", "MTGNM": "기획위원회", "PRMPST_CMIT_NM": "기획위원회"}

def record(text=MIXED, **kwargs):
    return E.make_record(dict(META), E.parse_turns(text), source="fixture", source_kind="SYNTHETIC", **kwargs)


def test_mixed_bold_plain_and_hidden_script():
    turns = E.parse_turns(MIXED)
    assert [t["label"] for t in turns] == ["위원장 최가상", "김가상 위원", "기획과장 이가상", "박가상 위원"]
    assert [t["role"] for t in turns] == ["chair", "member", "executive", "member"]
    assert "악성인" not in str(turns)
    assert turns[-1]["text"] == "언제요?"


def test_plain_colon_only_speakers_also_found_in_mixed_document():
    turns = E.parse_turns("○김가상 위원: 얼마입니까?\n기획과장 이가상: 2억원입니다.")
    assert len(turns) == 2
    assert turns[-1]["role"] == "executive"


def test_unknown_bulleted_content_is_not_a_speaker():
    turns = E.parse_turns("○기획과장 이가상: 업무보고를 드리겠습니다.\n○사업 추진\n사업비는 2억원입니다.")
    assert len(turns) == 1
    assert "사업비는 2억원" in turns[0]["text"]


def test_short_unanswered_question_survives():
    pairs = E.build_qa_pairs(E.parse_turns("○김가상 위원: 언제요?"))
    assert len(pairs) == 1 and pairs[0]["answers"] == []
    assert pairs[0]["answer_status"] == "NO_LINKED_ANSWER"


def test_cross_department_agenda_does_not_link():
    text = """○김가상 위원: 성인지예산 자료는 언제 제출합니까?
○기획과장 이가상: 다음 주까지 제출하겠습니다.
○위원장 최가상: 기획과 질의를 종결하겠습니다. 다음은 관광과 소관 업무보고입니다.
○관광과장 박가상: 주요업무를 보고드리겠습니다. 관련 사업을 추진하겠습니다."""
    pairs = E.build_qa_pairs(E.parse_turns(text))
    assert [a["label"] for a in pairs[0]["answers"]] == ["기획과장 이가상"]


def test_numbered_heading_is_a_hard_boundary():
    text = "○김가상 위원: 성인지예산 자료는 언제 제출합니까?\n2. 관광과 업무보고\n○관광과장 박가상: 관련 사업을 추진하겠습니다."
    turns = E.parse_turns(text)
    assert turns[0]["agenda"] != turns[-1]["agenda"]
    assert E.build_qa_pairs(turns)[0]["answers"] == []


def test_heading_does_not_silently_erase_unattributed_tail():
    turns = E.parse_turns("○김가상 위원: 얼마입니까?\n2. 관광과 업무보고\n발언자를 알 수 없는 설명입니다.\n○관광과장 박가상: 보고를 마칩니다.")
    assert any(t["role"] == "other" and "알 수 없는" in t["text"] for t in turns)


@pytest.mark.parametrize("keyword,text", [("성인지예산", "성인지 \u200b예산"), ("성인지예산", unicodedata.normalize("NFD", "성인지 예산")), ("rise", "ＲＩＳＥ 사업"), ("café", "cafe\u0301 사업")])
def test_unicode_space_variants(keyword, text):
    assert E.match_text(text, keyword)
    assert E.snippet("앞" * 50 + text + "뒤" * 50, keyword, width=3).startswith("…")
    assert text in E.snippet("앞" * 50 + text + "뒤" * 50, keyword, width=3)


def test_same_matching_for_qa_and_speech():
    r = record()
    assert len(E.record_events(r, "성인지예산", "질의답변")) == 1
    assert len(E.record_events(r, "성인지예산", "발언")) == 1


def test_standalone_report_only_appears_in_speech_mode():
    r = record("○기획과장 이가상: 성인지예산 업무보고를 드리겠습니다. 지표를 개선하겠습니다.")
    assert len(E.record_events(r, "성인지 예산", "발언")) == 1
    assert E.record_events(r, "성인지예산", "질의답변") == []
    assert E.record_events(r, "성인지예산", "약속") == []


def test_five_minute_mode_does_not_become_qa():
    r = record("○위원장 최가상: 다음은 5분 자유발언 순서입니다.\n○김가상 의원: 성인지예산 개선이 필요합니다.")
    assert len(E.record_events(r, "성인지예산", "5분자유발언")) == 1
    assert E.record_events(r, "성인지예산", "질의답변") == []


def test_unknown_mode_is_invalid_not_empty():
    with pytest.raises(E.EvidenceInputError):
        E.record_events(record(), mode="typo")


@pytest.mark.parametrize("sentence", ["추진하지 않겠습니다.", "작년에 검토하겠다고 했었습니다.", "오늘 회의에서 현황을 보고드리겠습니다."])
def test_non_commitments_excluded(sentence):
    assert E.classify_commitment(sentence) is None


def test_commitment_preserves_exact_excerpt_condition_and_no_completion_claim():
    text = "○김가상 위원: 성인지예산 자료 계획은 무엇입니까?\n○기획과장 이가상: 국비가 확보되면 내년에 수정하도록 하겠습니다."
    event = E.record_events(record(text), "성인지예산", "약속")[0]
    info = event["commitment"]
    assert info["type"] == "조건부 추진" and "국비" in info["condition"]
    assert info["status"] == "EVIDENCE_NOT_VERIFIED"
    answer = event["answers"][0]
    assert answer["text"][info["char_start"]:info["char_end"]] == info["excerpt"]
    assert event["metadata"]["fiscal_year"] is None


def test_complete_body_dedup_retains_distinct_tail_and_sitting():
    a = record("○김가상 위원: " + "본문" * 4000 + "첫번째 꼬리입니까?")
    b = copy.deepcopy(a); b["docid"] = "D2"; b["record_id"] = "r2"
    c = copy.deepcopy(a); c["turns"][0]["text"] += "다른 꼬리"
    d = copy.deepcopy(a); d["metadata"]["sitting"] = "2"
    result = E.dedup_records([a, b, c, d])
    assert len(result) == 3
    assert result[0]["aliases"][0]["docid"] == "D2"
    assert a["aliases"] == []


def test_incomplete_metadata_never_deduped():
    a = record(); a["metadata"]["term"] = None
    b = copy.deepcopy(a); b["docid"] = "D2"
    assert len(E.dedup_records([a, b])) == 2


def test_synthetic_is_not_merged_with_official_even_same_text():
    a = record(); b = copy.deepcopy(a); b["source_kind"] = "OFFICIAL_FETCHED"
    assert len(E.dedup_records([a, b])) == 2


def test_long_turn_paging_recovers_every_character_and_final_tail():
    text = "가나다" * 5000 + "마지막 원문"
    turns = E.parse_turns("○김가상 위원: " + text + "\n○기획과장 이가상: 답변 끝입니다.")
    collected = {i: "" for i in range(len(turns))}
    start_turn = start_char = 0
    for _ in range(20):
        page = E.read_page(turns, start_turn=start_turn, start_char=start_char, max_chars=1100)
        for piece in page["turns"]:
            collected[piece["idx"]] += piece["text"]
        if page["next_start_turn"] is None:
            break
        start_turn, start_char = page["next_start_turn"], page["next_start_char"]
    assert collected == {i: turn["text"] for i, turn in enumerate(turns)}
    assert "마지막 원문" in collected[0] and page["status"] == "COMPLETE"


def test_filtered_page_never_interprets_character_offset_on_other_turn():
    turns = E.parse_turns(MIXED)
    with pytest.raises(E.EvidenceInputError):
        E.read_page(turns, start_turn=0, start_char=1, selected_indices=[2])


@pytest.mark.parametrize("kwargs", [{"start_turn": True}, {"start_char": -1}, {"max_turns": 0}, {"max_chars": 0}, {"start_char": 999999}])
def test_invalid_paging_arguments(kwargs):
    with pytest.raises(E.EvidenceInputError):
        E.read_page(E.parse_turns(MIXED), **kwargs)


def test_cursor_is_bound_to_all_parameters_and_snapshot():
    params = {"keyword": "성인지예산", "council": "A", "date_from": "20250101"}
    cursor = E.encode_cursor(37, params, "snapshot-one")
    assert E.decode_cursor(cursor, params, "snapshot-one") == 37
    assert "성인지예산" not in cursor
    for changed, snapshot in [({**params, "council": "B"}, "snapshot-one"), (params, "snapshot-two")]:
        with pytest.raises(E.EvidenceInputError):
            E.decode_cursor(cursor, changed, snapshot)


def test_cursor_boolean_position_and_unknown_schema_rejected():
    valid = E.encode_cursor(1, {})
    payload = json.loads(base64.urlsafe_b64decode(valid[3:] + "=" * (-len(valid[3:]) % 4)))
    for field, value in [("p", True), ("v", 999)]:
        changed = dict(payload, **{field: value})
        bad = "e2." + base64.urlsafe_b64encode(json.dumps(changed).encode()).decode().rstrip("=")
        with pytest.raises(E.EvidenceInputError):
            E.decode_cursor(bad, {})


@pytest.mark.parametrize("start,end", [("2026-09-17", "2023-09-17"), ("2025-02-29", None), ("xx20250917", None), ("202509", None)])
def test_date_input_is_validated_without_coercion(start, end):
    with pytest.raises(E.EvidenceInputError):
        E.validate_date_range(start, end)


def test_status_distinguishes_empty_failure_and_partial():
    assert E.evidence_status(items=0, attempted=3, succeeded=3)["status"] == "EMPTY"
    assert E.evidence_status(items=0, attempted=3, succeeded=0, errors=["fetch failed"])["status"] == "ERROR"
    assert E.evidence_status(items=1, attempted=3, succeeded=2, errors=["page 2 failed"])["status"] == "PARTIAL"
    assert E.evidence_status(items=0, attempted=3, succeeded=3, limited=True)["status"] == "PARTIAL"
    assert E.evidence_status(items=0, attempted=1, succeeded=0, body_unavailable=1)["status"] == "ERROR"


def test_provided_origin_is_not_claimed_fetched_and_synthetic_never_promoted():
    r = record(source_url="https://council.example/minutes.pdf", body_url="https://viewer.example/show", source_url_verified=True, body_url_verified=True)
    assert r["provenance"]["source_url_status"] == "PROVIDED_NOT_FETCHED"
    assert r["provenance"]["body_url"] != r["provenance"]["source_url"]
    assert r["provenance"]["source_verified"] is False
    event = E.record_events(r, "성인지예산", "질의답변")[0]
    citation = event["question"]["citation"]
    assert citation["source_kind"] == "SYNTHETIC"
    assert citation["locator"] == "parsed_turn" and citation["fiscal_year"] is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://name:secret@example.com/", "https://example.com/\nX-Test: bad"])
def test_unsafe_provenance_reference_is_not_exposed(url):
    assert record(source_url=url)["provenance"]["source_url"] is None


def test_closing_bold_preserves_speaker_boundary_without_literal_whitespace():
    text = "가나다 " * 4000 + "끝표식"
    turns = E.parse_turns("<b>○기획과장 이가상</b>" + text)
    assert len(turns) == 1 and turns[0]["label"] == "기획과장 이가상"
    assert turns[0]["text"] == text
    pieces = E.read_page(turns, start_char=6000, max_chars=20000)
    assert "끝표식" in pieces["turns"][0]["text"]


def test_name_attached_to_member_title_is_supported():
    turns = E.parse_turns("○김가상위원: 언제요?")
    assert len(turns) == 1 and turns[0]["role"] == "member"


def test_credentialed_api_url_is_not_persisted_as_citation():
    url = "https://clik.nanet.go.kr/openapi/minutes.do?key=DO-NOT-DISCLOSE&docid=D1"
    r = record(body_url=url)
    assert r["provenance"]["body_url"] is None
    assert "DO-NOT-DISCLOSE" not in str(r)
    public = "https://www.gjsc.or.kr/record/recordView.do?key=abcdef"
    assert record(source_url=public)["provenance"]["source_url"] == public
