"""Evidence-preserving work products for administrative council preparation.

Input ``records`` is the event list returned by evidence_core.record_events.
This module is deliberately offline: it does not infer new facts, retrieve URLs,
rank people, or certify that an action mentioned in a meeting was performed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import OrderedDict
from typing import Any

SCHEMA_VERSION = "1.0"
MAX_EVENTS = 2000
MAX_INPUT_CHARS = 4_000_000
_SOURCE_LABELS = {
    "SYNTHETIC": "합성 시험자료",
    "USER_PROVIDED": "사용자 제공 자료·공개 원문 대조 미확인",
    "USER": "사용자 제공 자료·공개 원문 대조 미확인",
    "OFFICIAL": "공식 출처 수집자료·해석 및 현재 사실 별도 확인",
    "OFFICIAL_FETCHED": "공식 출처 수집자료·해석 및 현재 사실 별도 확인",
    "PUBLIC_API": "공개 API 수집자료·해석 및 현재 사실 별도 확인",
    "OFFICIAL_SITE": "의회 홈페이지 수집자료·해석 및 현재 사실 별도 확인",
    "LOCAL_ARCHIVE": "로컬 보관자료·공개 원문 대조 미확인",
    "CLIK": "CLIK 수집자료·해석 및 현재 사실 별도 확인",
    "COUNCIL_SITE": "의회 홈페이지 수집자료·해석 및 현재 사실 별도 확인",
}
_CITATION_KEYS = (
    "record_id", "docid", "turn_index", "source_url", "body_url", "source_kind",
    "body_sha256", "turn_sha256", "locator", "char_start", "char_end", "fiscal_year",
    "source_url_status", "body_url_status",
)
_META_KEYS = (
    "council", "council_name", "council_id", "meeting_date", "date", "committee",
    "meeting_name", "title", "term", "session", "sitting", "agenda_title", "fiscal_year",
)
_FACETS = (
    ("budget", "예산·재원", ("예산", "재원", "결산", "집행", "불용", "이월", "보조금", "단가"),
     "예산 산출근거와 집행현황, 재원 확보방안은 무엇입니까?",
     ["회계연도별 편성액·집행액·잔액", "국비·시비·구비 등 재원별 부담", "산출내역·단가·변동 사유"]),
    ("outcomes", "성과·효과", ("성과", "효과", "실적", "만족도", "지표", "달성", "참여율"),
     "목표 대비 실적과 주민이 체감하는 효과를 어떻게 확인하고 있습니까?",
     ["목표·실적 및 측정 기준", "전년과 동일 기준의 비교자료", "미달 사유와 보완계획"]),
    ("eligibility", "대상·형평성", ("대상", "선정", "자격", "형평", "사각지대", "수혜", "기준"),
     "지원대상과 선정기준은 무엇이며 형평성을 어떻게 확보합니까?",
     ["대상·선정기준의 근거", "신청·선정·탈락 현황", "접근성·누락대상 보완방안"]),
    ("implementation", "추진·운영", ("추진", "일정", "운영", "인력", "위탁", "지연", "공정", "계획"),
     "추진현황과 향후 일정, 운영상 보완사항은 무엇입니까?",
     ["현재 단계와 완료된 절차", "인력·운영·위탁 관리자료", "확정 일정과 조건부 일정 구분"]),
    ("legal_basis", "근거·절차", ("법령", "조례", "근거", "절차", "협의", "동의", "심의"),
     "사업의 근거와 필요한 사전절차는 무엇입니까?",
     ["기준일 현재 적용 법령·조례 원문", "의결·협의·심의 등 절차 이행자료", "조문 시행일과 적용대상"]),
    ("followup", "이전 답변 후속사항", ("지난", "전년", "작년", "후속", "약속", "조치결과", "반영"),
     "이전 회의에서 논의한 사항의 후속조치와 확인자료는 무엇입니까?",
     ["이전 답변 원문과 조건·기한", "조치계획·제출자료·실적보고", "미확인 사항과 추가 확인 담당"]),
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _events(records: list[dict]) -> tuple[list[dict], int]:
    if not isinstance(records, list) or len(records) > MAX_EVENTS:
        raise ValueError(f"records는 {MAX_EVENTS}건 이하의 근거 event 목록이어야 합니다.")
    try:
        if len(json.dumps(records, ensure_ascii=False)) > MAX_INPUT_CHARS:
            raise ValueError("근거 입력 크기가 허용 범위를 초과했습니다.")
    except (TypeError, OverflowError) as exc:
        raise ValueError("근거는 JSON으로 표현 가능한 값이어야 합니다.") from exc
    items, seen, duplicate_count = [], set(), 0
    for event in records:
        if not isinstance(event, dict):
            raise ValueError("각 근거 event는 객체여야 합니다.")
        if not any(k in event for k in ("question", "answers", "speech", "commitment")):
            raise ValueError("record_events가 반환한 question/answers/speech/commitment 형식이 필요합니다.")
        for name in ("question", "speech", "commitment"):
            if event.get(name) is not None and not isinstance(event[name], dict):
                raise ValueError(f"{name}은 객체 또는 null이어야 합니다.")
        answers = event.get("answers", [])
        if answers is None:
            answers = []
        if not isinstance(answers, list) or any(not isinstance(a, dict) for a in answers):
            raise ValueError("answers는 발언 객체 목록이어야 합니다.")
        # Only exact event copies are removed. Same dates, wording or IDs alone
        # cannot establish document identity or justify dropping another record.
        fingerprint = _digest(event)
        if fingerprint in seen:
            duplicate_count += 1
            continue
        seen.add(fingerprint)
        items.append(copy.deepcopy(event))
    return items, duplicate_count


def _topic(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError("topic은 1~300자의 주제여야 합니다.")
    return value.strip()


def _source_kind(event: dict, turn: dict | None = None) -> str:
    kind = _text(event.get("source_kind")).upper()
    citation = (turn or {}).get("citation")
    if isinstance(citation, dict):
        supplied_kind = _text(citation.get("source_kind")).upper()
        # A synthetic marker at either level always remains synthetic.
        if "SYNTHETIC" in (kind, supplied_kind):
            return "SYNTHETIC"
        # A user or archive record does not become fetched official evidence
        # merely because one nested citation claims an official source type.
        for unverified_kind in ("USER_PROVIDED", "USER", "LOCAL_ARCHIVE", "UNKNOWN"):
            if unverified_kind in (kind, supplied_kind):
                return unverified_kind
        kind = kind or supplied_kind
    return kind or "UNKNOWN"


def _quote(turn: dict | None, event: dict) -> dict | None:
    if not turn or not _text(turn.get("text")).strip():
        return None
    supplied = turn.get("citation")
    supplied = supplied if isinstance(supplied, dict) else {}
    citation = {k: copy.deepcopy(supplied.get(k)) for k in _CITATION_KEYS}
    citation["record_id"] = citation["record_id"] or event.get("record_id")
    citation["docid"] = citation["docid"] or event.get("docid")
    if citation["turn_index"] is None:
        citation["turn_index"] = turn.get("turn_index")
    source_kind = _source_kind(event, turn)
    citation["source_kind"] = source_kind
    body = turn["text"]  # Preserve original text, punctuation and whitespace.
    located = bool(citation["record_id"] or citation["docid"]) and citation["turn_index"] is not None
    return {
        "text": body,
        "label": _text(turn.get("label")),
        "role": _text(turn.get("role")),
        "act": _text(turn.get("act")),
        "agenda": copy.deepcopy(turn.get("agenda")),
        "citation": citation,
        "quote_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "source_kind": source_kind,
        "source_label": _SOURCE_LABELS.get(source_kind, "출처 유형 확인 필요"),
        "locator_status": "LOCATED_IN_INPUT" if located else "LOCATOR_INCOMPLETE",
        "fact_status": "STATEMENT_ONLY_CURRENT_FACT_NOT_VERIFIED",
    }


def _metadata(event: dict) -> dict:
    source = event.get("metadata")
    source = source if isinstance(source, dict) else {}
    data = {k: copy.deepcopy(source[k]) for k in _META_KEYS if k in source}
    data.setdefault("fiscal_year", None)
    return data


def _reference(event: dict) -> dict:
    return {
        "event_id": event.get("event_id") or "event-" + _digest(event)[:20],
        "record_id": event.get("record_id"),
        "docid": event.get("docid"),
        "metadata": _metadata(event),
        "source_kind": _source_kind(event),
        "provenance": copy.deepcopy(event.get("provenance")),
        "coverage_note": copy.deepcopy(event.get("coverage_note")),
    }


def _document_key(row: dict) -> str | None:
    value = row.get("record_id") or row.get("docid")
    return str(value) if value else None


def _envelope(kind: str, events: list[dict], coverage: dict | None, duplicates: int) -> dict:
    if coverage is not None and not isinstance(coverage, dict):
        raise ValueError("coverage는 객체 또는 null이어야 합니다.")
    supplied = copy.deepcopy(coverage) if coverage else {}
    upstream_status = str(supplied.get("status", "UNKNOWN")).upper()
    # Output success describes the transform, not complete search coverage.
    status = "OK" if events else "EMPTY"
    if upstream_status in {"PARTIAL", "ERROR", "UNKNOWN"}:
        status = "PARTIAL" if events else ("ERROR" if upstream_status == "ERROR" else "EMPTY")
    return {
        "schema_version": SCHEMA_VERSION,
        "workflow": kind,
        "status": status,
        "upstream_status": upstream_status,
        "coverage": supplied,
        "input_event_count": len(events),
        "supplied_document_count": len({k for row in events if (k := _document_key(row))}),
        "unidentified_source_event_count": sum(_document_key(row) is None for row in events),
        "exact_duplicate_events_removed": duplicates,
        "human_review_required": True,
        "scope_note": "제공된 근거 묶음 범위의 검토자료이며 전체 의회의 논의·현재 사실·이행 여부를 판정하지 않습니다.",
        "neutrality_note": "공개된 정책 논의와 답변 근거를 정리하며 의원별 성향·평가·질문 확률을 산출하지 않습니다.",
    }


def _qa_rows(events: list[dict]) -> list[dict]:
    rows, seen = [], set()
    for event in events:
        question = _quote(event.get("question"), event)
        if question is None:
            continue
        answers = [q for turn in (event.get("answers") or []) if (q := _quote(turn, event))]
        # A commitment event may repeat the question. Keep one QA row if and
        # only if the complete input question+answers and source are identical.
        fingerprint = _digest([event.get("record_id"), question, answers])
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append({**_reference(event), "question": question, "answers": answers,
                     "answer_link_status": "LINKED_IN_INPUT" if answers else "NOT_LINKED_IN_SCOPE"})
    return rows


def build_faq_candidates(records: list[dict], *, topic: str,
                         coverage: dict | None = None, limit: int = 10) -> dict:
    """Group existing questions exactly; provide labeled preparation prompts.

    Frequency counts are within the supplied sample only. No semantic grouping,
    person-level statistic, future-question prediction or newly invented answer.
    """
    topic = _topic(topic)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit은 1~50의 정수여야 합니다.")
    events, duplicates = _events(records)
    result = _envelope("faq_candidates", events, coverage, duplicates)
    groups: dict[str, list[dict]] = OrderedDict()
    for row in _qa_rows(events):
        groups.setdefault(_key(row["question"]["text"]), []).append(row)
    candidates = []
    # Stable by first appearance at equal count; only counts of source records.
    ordered = sorted(groups.values(), key=lambda rows: -len({k for r in rows if (k := _document_key(r))}))
    for rows in ordered[:limit]:
        question_text = rows[0]["question"]["text"]
        facets = []
        for facet_id, label, terms, prompt, documents in _FACETS:
            if any(_key(term) in _key(question_text) for term in terms):
                facets.append({"id": facet_id, "label": label, "suggested_preparation_question": prompt,
                               "required_documents": list(documents), "status": "AUTHORING_SUGGESTION"})
        if not facets:
            facets = [{"id": "general", "label": "사업 현황", "suggested_preparation_question": f"{topic} 관련 현재 현황과 추가 확인사항은 무엇입니까?",
                       "required_documents": ["최신 사업현황", "이전 논의 이후 변경사항", "답변 내용의 근거자료"], "status": "AUTHORING_SUGGESTION"}]
        distinct_records = {k for r in rows if (k := _document_key(r))}
        candidates.append({
            "candidate_id": "faq-" + _digest(question_text)[:16],
            "label": "근거 질문 기반 준비 후보",
            "source_question": question_text,
            "occurrence_count_in_supplied_records": len(distinct_records),
            "supplied_document_count": result["supplied_document_count"],
            "unidentified_source_occurrences": sum(_document_key(row) is None for row in rows),
            "frequency_definition": "공백·Unicode 표기만 정규화하여 같은 질문이 확인된 식별 가능한 제공 문서 수",
            "question_occurrences": rows,
            "preparation_facets": facets,
            "current_answer": None,
            "current_answer_status": "CURRENT_SUPPORTING_DOCUMENTS_REQUIRED",
            "answer_fields_to_complete": ["현재 확인된 사실 및 기준일", "과거 답변과의 변경사항·사유", "확정된 조치와 추가 검토사항"],
        })
    result.update({"topic": topic, "candidates": candidates, "total_candidate_count": len(groups),
                   "returned_candidate_count": len(candidates), "truncated": len(groups) > limit,
                   "omitted_candidate_count": max(0, len(groups) - limit),
                   "generation_note": "준비 질문은 실무 검토용 제안이며 실제 발언·향후 질문 예측이 아닙니다. 과거 답변은 당시 발언입니다."})
    if not candidates and events:
        result["status"] = "PARTIAL"
        result["empty_reason"] = "제공 근거에서 질문으로 연결된 발언을 찾지 못했습니다. 보고·설명을 질문으로 변환하지 않았습니다."
    return result


def build_followup_ledger(records: list[dict], *, coverage: dict | None = None) -> dict:
    """Return commitments only as unverified follow-up candidates."""
    events, duplicates = _events(records)
    result = _envelope("followup_ledger", events, coverage, duplicates)
    entries, seen = [], set()
    for event in events:
        commitment = event.get("commitment")
        if not commitment:
            continue
        answers = [q for turn in (event.get("answers") or []) if (q := _quote(turn, event))]
        speech = _quote(event.get("speech"), event)
        if speech and speech["role"] in {"executive", "official", "staff", "department", "답변자", "집행부"}:
            answers.append(speech)
        excerpt = _text(commitment.get("excerpt") or commitment.get("text") or commitment.get("sentence"))
        matched = []
        for answer in answers:
            if excerpt and excerpt in answer["text"]:
                matched.append(answer)
        # A supplied excerpt that cannot be found is never made into a quote.
        verified_excerpt = excerpt if matched else None
        source_answers = matched or answers
        condition = _text(commitment.get("condition")) or None
        deadline = _text(commitment.get("deadline")) or None
        corpus = verified_excerpt or "\n".join(a["text"] for a in source_answers)
        # Preserve textual qualifiers only when present verbatim in source.
        condition_verified = condition is not None and condition in corpus
        deadline_verified = deadline is not None and deadline in corpus
        signature = _digest([event.get("record_id"), verified_excerpt, source_answers,
                             commitment.get("type"), condition, deadline])
        if signature in seen:
            continue
        seen.add(signature)
        candidate_citation = None
        if verified_excerpt:
            answer = matched[0]
            candidate_citation = copy.deepcopy(answer["citation"])
            start = answer["text"].find(verified_excerpt)
            supplied_start = commitment.get("char_start")
            if (isinstance(supplied_start, int) and supplied_start >= 0
                    and answer["citation"].get("turn_index") == commitment.get("turn_index")
                    and answer["text"][supplied_start:supplied_start + len(verified_excerpt)] == verified_excerpt):
                start = supplied_start
            candidate_citation["char_start"] = start
            candidate_citation["char_end"] = start + len(verified_excerpt)
        entries.append({
            "entry_id": "followup-" + signature[:20],
            **_reference(event),
            "question": _quote(event.get("question"), event),
            "commitment_type": _text(commitment.get("type")) or "분류 확인 필요",
            "classification_status": "RULE_BASED_CANDIDATE_REVIEW_REQUIRED",
            "candidate_excerpt": verified_excerpt,
            "candidate_citation": candidate_citation,
            "excerpt_status": "EXACT_SUBSTRING" if verified_excerpt else "SOURCE_SENTENCE_REVIEW_REQUIRED",
            "source_answers": source_answers,
            "condition_verbatim": condition if condition_verified else None,
            "condition_status": "SOURCE_TEXT" if condition_verified else "NOT_VERIFIED",
            "deadline_verbatim": deadline if deadline_verified else None,
            "deadline_status": "SOURCE_TEXT" if deadline_verified else "NOT_VERIFIED",
            "calendar_due_date": None,
            "owner_department": None,
            "fulfillment_status": "EVIDENCE_NOT_VERIFIED",
            "fulfillment_label": "후속 증빙 미확인",
            "required_evidence": ["조치계획 또는 담당부서 확인자료", "제출·시행·수정 내용을 확인할 원문", "확인 기준일 및 증빙 위치"],
            "review_fields": {"reviewer": None, "checked_at": None, "supporting_document_ref": None, "notes": None},
        })
    result.update({"entries": entries, "entry_count": len(entries),
                   "ledger_note": "조건·기한은 원문에 있는 표현만 보존합니다. 발언자 직함으로 현재 담당부서나 이행 완료 여부를 정하지 않습니다."})
    return result


def build_briefing(records: list[dict], *, topic: str, council: str | None = None,
                   coverage: dict | None = None, max_evidence: int = 12,
                   include_derived: bool = True) -> dict:
    """Produce a reviewable briefing skeleton with exact source quotations.

    ``max_evidence`` caps the quotation rows: a single meeting can hold hundreds
    of speeches, and an unbounded briefing does not fit any model context.
    Omitted rows are reported, never dropped in silence. ``include_derived``
    embeds the follow-up ledger and question candidates; a caller that already
    returns those sections separately passes False to avoid duplicating them.
    """
    topic = _topic(topic)
    if council is not None and (not isinstance(council, str) or len(council) > 200):
        raise ValueError("council은 200자 이하의 문자열 또는 null이어야 합니다.")
    if isinstance(max_evidence, bool) or not isinstance(max_evidence, int) or not 1 <= max_evidence <= 200:
        raise ValueError("max_evidence는 1~200의 정수여야 합니다.")
    events, duplicates = _events(records)
    result = _envelope("briefing", events, coverage, duplicates)
    discussions = _qa_rows(events)
    source_speeches, seen = [], set()
    for event in events:
        speech = _quote(event.get("speech"), event)
        if not speech:
            continue
        fingerprint = _digest([event.get("record_id"), speech])
        if fingerprint not in seen:
            source_speeches.append({**_reference(event), "speech": speech})
            seen.add(fingerprint)
    ledger = build_followup_ledger(events, coverage=coverage) if include_derived else None
    faq = build_faq_candidates(events, topic=topic, coverage=coverage) if include_derived else None
    kept_evidence, kept_speech = discussions[:max_evidence], source_speeches[:max_evidence]
    result.update({
        "title": f"{topic} 의회 논의 및 답변 준비자료",
        "topic": topic, "requested_council": council,
        "discussion_evidence": kept_evidence,
        "other_speech_evidence": kept_speech,
        "evidence_totals": {
            "discussion_evidence_total": len(discussions),
            "discussion_evidence_shown": len(kept_evidence),
            "other_speech_evidence_total": len(source_speeches),
            "other_speech_evidence_shown": len(kept_speech),
            "shown_selection": "입력 근거 순서의 앞에서부터; 중요도 순위가 아님",
            "retrieval": "생략분은 council_evidence_bundle의 item_offset으로 이어봅니다.",
        },
        "followup_candidates": ledger["entries"] if ledger else None,
        "preparation_questions": faq["candidates"] if faq else None,
        "derived_sections": ("briefing 내부 포함" if include_derived else
                             "followup_ledger·question_candidates 절에서 각각 1회만 제공"),
        "answer_outline": [
            {"section": "질의 취지", "content": None, "instruction": "원문에서 확인되는 정책 쟁점을 정리하고 발언 의도를 추정하지 않음"},
            {"section": "확인된 현황", "content": None, "instruction": "기준일·회계연도·수치 단위와 근거를 붙여 현재 현황을 기재"},
            {"section": "그간 조치", "content": None, "instruction": "과거 답변 원문과 실제 조치 증빙을 구분하여 기재"},
            {"section": "향후 계획", "content": None, "instruction": "확정 사항·검토 사항을 구분하고 조건·기한은 확인된 범위에서 기재"},
        ],
        "unresolved_checks": [
            "검색기간·의회·위원회·원문 제공 범위 확인",
            "회의연도와 예산·결산 회계연도 구분",
            "당시 답변 이후 변경된 현황·수치 확인",
            "타 의회 사례의 우리 지역 적용조건 확인",
        ],
        "editorial_note": "원문 인용은 표현을 바꾸지 않았습니다. 답변 문안은 근거 확인 후 존중하는 공무원 문체로 작성해야 합니다.",
    })
    return result
