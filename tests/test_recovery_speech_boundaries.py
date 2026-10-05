"""Independent counterexamples for reports incorrectly linked as answers."""
import pytest

import evidence_core as E


@pytest.mark.parametrize("report_name", [
    "업무추진실적", "업무 추진 실적", "업무추진계획", "업무 추진 계획", "업무",
])
def test_formal_report_keeps_its_source_without_becoming_a_question_answer(report_name):
    report = (
        "안녕하십니까? 환경과장입니다. 위원님들의 노고에 감사드립니다. "
        f"환경과 소관 2026년도 {report_name} 보고를 드리겠습니다. "
        "문화공간 조성 사업에 대해 설명드리겠습니다."
    )
    turns = E.parse_turns(
        "○김가상 위원: 폐기물 감량 사업은 어떻게 됩니까?\n"
        f"○환경과장 이가상: {report}"
    )
    assert turns[1]["act"] == "report"
    pairs = E.build_qa_pairs(turns, "폐기물")
    assert len(pairs) == 1
    assert pairs[0]["answers"] == []
    assert pairs[0]["answer_status"] == "NO_LINKED_ANSWER"
    record = E.make_record({"DOCID": "SYNTHETIC_REPORT", "MTG_DE": "20261005"}, turns, source="CLIK")
    speeches = E.record_events(record, "문화공간", mode="발언")
    assert len(speeches) == 1
    assert speeches[0]["speech"]["text"] == report
    assert speeches[0]["speech"]["act"] == "report"


@pytest.mark.parametrize("answer", [
    "위원님 질의에 답변드리겠습니다. 폐기물 감량 사업을 추진하고 있습니다.",
    "질문하신 폐기물 감량 사업을 설명드리겠습니다. 관련 시설을 운영하고 있습니다.",
    "답변드리겠습니다. 폐기물 감량 사업을 추진하고 있습니다. 다음 회기에는 업무보고를 드리겠습니다.",
])
def test_explicit_question_response_is_preserved(answer):
    turns = E.parse_turns(
        "○김가상 위원: 폐기물 감량 사업은 어떻게 됩니까?\n"
        f"○환경과장 이가상: {answer}"
    )
    assert turns[1]["act"] == "answer_candidate"
    pairs = E.build_qa_pairs(turns, "폐기물")
    assert [turn["text"] for turn in pairs[0]["answers"]] == [answer]


def test_report_promise_to_answer_later_is_not_a_current_answer():
    report = "환경과 소관 업무보고를 드리겠습니다. 보고가 끝나면 위원님 질의에 답변드리겠습니다."
    turns = E.parse_turns(
        "○김가상 위원: 폐기물 감량 사업은 어떻게 됩니까?\n"
        f"○환경과장 이가상: {report}"
    )
    assert turns[1]["act"] == "report"
    assert E.build_qa_pairs(turns, "폐기물")[0]["answers"] == []


def test_answer_before_new_formal_report_is_kept_without_appending_that_report():
    turns = E.parse_turns(
        "○김가상 위원: 폐기물 감량 사업은 어떻게 됩니까?\n"
        "○환경과장 이가상: 폐기물 감량 사업은 올해 시행하였습니다.\n"
        "○문화과장 박가상: 문화과 소관 업무 추진 계획 보고를 드리겠습니다. 문화공간을 설명드리겠습니다."
    )
    answers = E.build_qa_pairs(turns, "폐기물")[0]["answers"]
    assert [turn["label"] for turn in answers] == ["환경과장 이가상"]
