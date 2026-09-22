"""부서 관점 정리·반복 쟁점 집계·기관 서식 배치의 순수 함수.

실무의 단위는 주제어가 아니라 소관 부서다. 담당자는 "성인지예산"을 검색하기 전에
"우리 과가 의회에서 무엇을 받았는가"를 먼저 알아야 한다. 이 모듈은 이미 수집된
근거 event 목록을 받아 부서 기준으로 나누고, 여러 회의연도에 걸친 반복을 세고,
기관 서식의 칸에 배치한다.

네트워크·파일 접근·외부 모델 호출이 없다. 사실을 만들어 넣지 않으며, 확인되지
않은 칸은 비워 둔 채 담당자 확인 대상으로 표시한다.
"""
from __future__ import annotations

import datetime as dt
import copy
import hashlib
import department_aliases as A
import recurrence_core as Q
import re
import unicodedata
from typing import Any, Callable, Iterable, Optional

NOTE = "실무 검토자료입니다. 원문 인용·담당자 제공자료·준비 제안을 구분하며 최종 제출은 담당자가 확인합니다."
BLANK = None
CONFIRM = "담당자 확인 필요"

# 직함 뒤에 붙는 말을 떼어 부서 어간을 얻는다. '미래전략과장'·'미래전략팀장'을 같은 부서로 본다.
_ROLE_TAIL = re.compile(
    r"(부서장|담당관|과장|팀장|국장|실장|소장|단장|센터장|본부장|원장|관장|계장|주무관|사무관|"
    r"과|팀|국|실|소|단|센터|본부)$")
_STOP_STEM = {"의회", "위원", "의원", "위원장", "의장", "직무", "대리"}


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def department_stem(name: str) -> str:
    """'기획실' → '기획', '미래전략과장' → '미래전략'. 어간이 짧으면 원문을 유지한다."""
    stem = normalize(name)
    for _ in range(2):
        cut = _ROLE_TAIL.sub("", stem)
        if cut == stem or len(cut) < 2:
            break
        stem = cut
    return stem if len(stem) >= 2 and stem not in _STOP_STEM else normalize(name)


def matches_department(label: str, department: str) -> bool:
    """발언자 표기가 그 부서인지 판단. 어간 일치까지 허용해 대리답변을 놓치지 않는다."""
    if not department:
        return False
    lab, dept = normalize(label), normalize(department)
    if not lab:
        return False
    if dept and dept in lab:
        return True
    stem = department_stem(department)
    return len(stem) >= 2 and stem in lab


def _quote_of(node: Any) -> Optional[dict]:
    return node if isinstance(node, dict) else None


def _speaker(node: Any) -> str:
    """발언자 표기. 파서는 'label'로, 정리된 인용은 'speaker'로 담는다."""
    quote = _quote_of(node)
    if not quote:
        return ""
    return str(quote.get("label") or quote.get("speaker") or "")


def _text_of(node: Any) -> str:
    quote = _quote_of(node)
    return str(quote.get("text") or "") if quote else ""


def _meta(event: dict) -> dict:
    meta = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    return {"meeting_date": meta.get("meeting_date"), "council_name": meta.get("council_name"),
            "meeting_name": meta.get("meeting_name"), "session": meta.get("session"),
            "fiscal_year": meta.get("fiscal_year")}


def meeting_year(event: dict) -> Optional[str]:
    """회의연도. 회계연도가 아니며, 원문에 회의일이 없으면 None으로 둔다."""
    day = A.event_date(event)
    return str(day.year) if day else None


def format_meeting_date(raw: Any) -> str:
    """'20261225' → '2026.12.25.'. 공문서 표기다. 8자리가 아니면 원문을 그대로 둔다."""
    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) == 8:
        return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}."
    return text


def _citation(event: dict) -> dict:
    return {"event_id": event.get("event_id"), "record_id": event.get("record_id"),
            "docid": event.get("docid"), "source_kind": event.get("source_kind"),
            "provenance": copy.deepcopy(event.get("provenance", {})),
            "metadata": _meta(event),
            "retrieval": "council_read_source(ref=docid)로 원문을 확인합니다."}


def _preserve_quote(node: dict) -> dict:
    # Do not discard turn indexes, character offsets, or source URLs.
    return {**copy.deepcopy(node), "speaker": _speaker(node), "text": _text_of(node)}


def classify_department_events(events: Iterable[dict], department: str,
                               aliases: Optional[list[dict]] = None) -> dict:
    """분류에 사용한 명칭을 기록하고, 날짜가 불명확한 유효기간 별칭은 보류한다."""
    answered, unanswered, other, unresolved = [], [], [], []
    for event in events:
        if not isinstance(event, dict):
            continue
        names, pending = A.applicable_names(event, department, aliases or [])
        answers = [a for a in (event.get("answers") or []) if _quote_of(a)]
        mine = [a for a in answers if any(matches_department(_speaker(a), n) for n in names)]
        matched_names = [n for n in names if any(matches_department(_speaker(a), n) for a in mine)]
        question = event.get("question") or event.get("speech")
        mentioned_names = [n for n in names if matches_department(_text_of(question), n)]
        row = {**_citation(event),
               "question": _preserve_quote(question) if question else None,
               "answers": [_preserve_quote(a) for a in (mine or answers)],
               "answer_link_status": "LINKED_IN_SCOPE" if answers else "NOT_LINKED_IN_SCOPE",
               "matched_department_names": list(dict.fromkeys(matched_names + mentioned_names)),
               "alias_basis": "USER_PROVIDED_NOT_INDEPENDENTLY_VERIFIED" if
                   any(n != department for n in matched_names + mentioned_names) else "PRIMARY_LABEL"}
        if mine:
            row["matched_by"] = "답변자 직함이 지정 부서 또는 적용기간 내 사용자 지정 별칭과 일치"
            answered.append(row)
        elif mentioned_names and not answers:
            row["matched_by"] = "질의 본문에서 부서 거론, 확인 범위에 답변 미연결"
            unanswered.append(row)
        elif mentioned_names:
            row["matched_by"] = "부서 거론, 다른 발언자가 답변"
            other.append(row)
        elif pending and any(matches_department(_text_of(question), n) or
                             any(matches_department(_speaker(a), n) for a in answers) for n in pending):
            row.update(matched_by="회의일 미확인: 별칭 적용기간 판단 보류", pending_aliases=pending)
            unresolved.append(row)
    return {"answered": answered, "unanswered": unanswered, "other_mention": other,
            "alias_date_unresolved": unresolved}


def event_touches_department(event: dict, department: str, aliases: Optional[list[dict]] = None) -> bool:
    if not isinstance(event, dict) or not department:
        return False
    names, _ = A.applicable_names(event, department, aliases or [])
    return any(matches_department(_text_of(event.get("question") or event.get("speech")), n) or
               any(matches_department(_speaker(a), n) for a in event.get("answers", [])) for n in names)


# 반복 쟁점 집계에서 걸러낼 내용 없는 말. 주제어가 아니라 서술어에 가깝다.
GENERIC_TERMS = ("원인", "규모", "현황", "실적", "이유", "상황", "결과", "기준", "수준",
                 "대상", "관리", "운영", "조치", "개선", "지적")


def department_commitments(events: Iterable[dict], department: str,
                           aliases: Optional[list[dict]] = None) -> list[dict]:
    """우리 부서 답변에서 나온 후속조치 '후보'. 이행 여부는 판정하지 않는다.

    같은 발언이 여러 회의록 사본에 실리면 문면이 같은 항목이 겹친다. 유형·문면·기한이
    같은 회의 안에서 같으면 한 번만 싣되, 다른 회의·유형이면 각각 남긴다.
    """
    out = []
    seen: set[tuple] = set()
    for event in events:
        commitment = event.get("commitment") if isinstance(event, dict) else None
        if not commitment:
            continue
        answers = [a for a in (event.get("answers") or []) if _quote_of(a)]
        names, _ = A.applicable_names(event, department, aliases or [])
        mine = [a for a in answers if any(matches_department(_speaker(a), n) for n in names)]
        if not mine:
            continue
        meta = event.get("metadata") or {}
        # Same wording in a later meeting is a distinct follow-up candidate.
        meeting = tuple(meta.get(k) for k in ("council_id", "meeting_date", "session", "meeting_name"))
        if not meta.get("meeting_date"):
            meeting = (event.get("record_id") or event.get("docid"),)
        mark = (meeting, commitment.get("type"), hashlib.sha256(normalize(_text_of(mine[0])).encode()).hexdigest(),
                normalize(commitment.get("deadline")))
        if mark in seen:
            continue
        seen.add(mark)
        out.append({**_citation(event),
                    "commitment_type": commitment.get("type"),
                    "condition_verbatim": commitment.get("condition"),
                    "deadline_verbatim": commitment.get("deadline"),
                    "answerer": _speaker(mine[0]),
                    "answer_evidence": _preserve_quote(mine[0]),
                    "excerpt": _text_of(mine[0])[:400],
                    "fulfillment_status": "EVIDENCE_NOT_VERIFIED",
                    "fulfillment_note": "후속 증빙 미확인이며 미이행 판정이 아닙니다."})
    return out


# ── 반복 쟁점 ──────────────────────────────────────────────────────────────
def recurring_terms(events: Iterable[dict], extract: Callable[[str], list[str]],
                    *, min_years: int = 2, top: int = 15,
                    stopwords: Iterable[str] = ()) -> dict:
    """여러 회의연도에 반복 등장한 주제어를 센다.

    질의 성격의 발언만 센다. 답변에 나온 말을 의회의 요구로 세면 방향이 뒤집힌다.
    집계 단위는 연도·회의이며 의원 개인이 아니다. 결과는 '반복 확인'이지
    다음 회기의 질문 예측이 아니다.
    """
    if not isinstance(min_years, int) or isinstance(min_years, bool) or min_years < 1:
        raise ValueError("min_years는 1 이상의 정수여야 합니다.")
    if not isinstance(top, int) or isinstance(top, bool) or not 1 <= top <= 60:
        raise ValueError("top은 1~60의 정수여야 합니다.")
    skip = {normalize(x) for x in stopwords if str(x).strip()}
    years_seen: set[str] = set()
    table: dict[str, dict[str, Any]] = {}
    undated = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        question = event.get("question") or (event.get("speech") if event.get("kind") == "speech" else None)
        body = _text_of(question)
        if not body:
            continue
        year = meeting_year(event)
        if year is None:
            undated += 1
            continue
        years_seen.add(year)
        doc = str(event.get("record_id") or event.get("docid") or "")
        for term in dict.fromkeys(extract(body)):
            if normalize(term) in skip or len(term) < 2:
                continue
            row = table.setdefault(term, {"years": set(), "documents": set(), "citations": [], "cue_types": set()})
            cues = Q.request_cues(body, term)
            row["cue_types"].update(cues["cue_types"])
            row["years"].add(year)
            row["documents"].add(doc)
            if len(row["citations"]) < 3 and not any(c["record_id"] == event.get("record_id")
                                                     for c in row["citations"]):
                row["citations"].append({**_citation(event), "excerpt": body[:200], "request_cues": cues})
    ranked = sorted(
        ((term, row) for term, row in table.items() if len(row["years"]) >= min_years),
        key=lambda kv: (-len(kv[1]["years"]), -len(kv[1]["documents"]), kv[0]))
    items = [{"term": term,
              "year_count": len(row["years"]),
              "years": sorted(row["years"]),
              "document_count": len(row["documents"]),
              "citations": row["citations"],
              "citation_documents_total": len(row["documents"]),
              "citation_documents_omitted": max(0, len(row["documents"])-len(row["citations"])),
              "classification": "REPEATED_TOPIC_CANDIDATE",
              "same_request_confirmed": False,
              "review_status": "MANUAL_CONTEXT_REVIEW_REQUIRED",
              "cue_types": sorted(row["cue_types"]),
              "contrasting_cues_detected": {"EXPAND_OR_START_CUE", "DEFER_OR_STOP_CUE"} <= row["cue_types"],
              "interpretation_warning": "같은 단어의 재등장은 같은 방향의 요구 반복을 입증하지 않습니다."}
             for term, row in ranked[:top]]
    return {"items": items, "observed_years": sorted(years_seen), "undated_events": undated,
            "total_candidate_terms": len(ranked), "omitted_candidate_terms": max(0, len(ranked)-len(items)),
            "counting_basis": "질의 성격 발언의 주제어를 회의연도·문서 단위로 셉니다. 답변 발언은 세지 않습니다.",
            "limitations": [
                "결과는 반복 주제어 후보이며 동일 요구·요구 방향의 일치를 자동 확정하지 않습니다.",
                "확인한 회의록 범위의 반복이며 해당 의회 전체의 반복 빈도가 아닙니다.",
                "형태소 분석기 없이 조사·어미를 규칙으로 제거한 주제어라 잡음이 섞일 수 있습니다.",
                "반복 확인이며 다음 회기의 질문 예측이나 질문 확률이 아닙니다.",
                "의원 개인 단위로 집계하지 않습니다.",
            ]}


# ── 기관 서식 ──────────────────────────────────────────────────────────────
FORMS: dict[str, dict[str, Any]] = {
    "5분자유발언_회의자료": {
        "title_suffix": "5분 자유발언 관련 회의자료",
        "marks": ["☐", "○", "-", "·"],
        "sections": [
            ("개    요", "발언 의원·발언 일자·주요 내용을 원문 기준으로 적습니다.", "evidence"),
            ("현 실태", "기준일을 붙인 현재 현황·수치를 부서 자료에서 적습니다.", "facts"),
            ("검토결과", "수용·중장기 검토·법령상 곤란을 구분하고 사유와 대안을 적습니다.", "blank"),
            ("행정사항", "조치 내용·담당부서·일정을 적습니다.", "commitments"),
        ]},
    "구정질문_답변서": {
        "title_suffix": "구정질문 답변자료",
        "marks": ["☐", "○", "-", "·"],
        "sections": [
            ("질문요지", "질문 원문을 요약하지 말고 쟁점 단위로 적습니다.", "evidence"),
            ("현    황", "기준일·단위·출처를 붙여 적습니다.", "facts"),
            ("답변요지", "확인된 사실과 검토 중 사항을 구분해 적습니다.", "blank"),
            ("향후계획", "확정 사항과 조건부 사항을 구분해 적습니다.", "commitments"),
        ]},
    "행정사무감사_답변카드": {
        "title_suffix": "행정사무감사 답변카드",
        "marks": ["☐", "○", "-", "·"],
        "sections": [
            ("질의요지", "확인된 질의 원문과 회의 정보를 적습니다.", "evidence"),
            ("관련근거", "법령·조례·계획 근거를 시행일과 함께 적습니다.", "blank"),
            ("현    황", "기준일 현재 수치를 단위와 함께 적습니다.", "facts"),
            ("답변요지", "질의에 직접 답하고 과거 답변과 현재 사실을 구분합니다.", "blank"),
            ("후속조치", "지난 답변의 조치 경과와 증빙 확인 여부를 적습니다.", "commitments"),
        ]},
    "1페이지_검토보고": {
        "title_suffix": "검토보고",
        "marks": ["□", "○", "-", "·"],
        "sections": [
            ("추진배경", "의회 논의 경과와 필요성을 근거와 함께 적습니다.", "evidence"),
            ("주요내용", "확인된 현황·수치를 기준일과 함께 적습니다.", "facts"),
            ("검토의견", "쟁점별 판단과 곤란 사유·대안을 적습니다.", "blank"),
            ("행정사항", "조치 사항·담당부서·일정을 적습니다.", "commitments"),
        ]},
}


def pad_label(label: str, width: int = 4) -> str:
    """'개요'를 '개    요'로 벌려 4자폭에 맞춘다. 공무원 문서의 통상 표기다."""
    raw = str(label or "")
    text = re.sub(r"\s+", "", raw)
    if len(text) >= width or raw != text:
        # 이미 띄어 쓴 항목명('현 실태')은 기관 표기를 그대로 둔다.
        return raw
    if len(text) == 2:
        return (" " * (2 * (width - len(text)))).join(text)
    return text


def _fact_line(fact: dict) -> str:
    bits = [str(fact.get("text") or "").strip()]
    tail = " / ".join(str(fact.get(k)) for k in ("document_ref", "as_of", "unit") if fact.get(k))
    if tail:
        bits.append(f"({tail})")
    return " ".join(bits)


def build_worksheet(form: str, *, topic: str, department: str, council: str,
                    evidence: Optional[list[dict]] = None,
                    facts: Optional[list[dict]] = None,
                    commitments: Optional[list[dict]] = None,
                    prepared_on: Optional[str] = None) -> dict:
    """확인된 근거·제공자료를 기관 서식 칸에 배치한다.

    빈칸은 비운 채 '담당자 확인 필요'로 남긴다. 현황·판단 문장을 만들어 넣지 않는다.
    """
    if form not in FORMS:
        raise ValueError("서식은 " + ", ".join(FORMS) + " 중 하나입니다.")
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
        raise ValueError("topic은 1~200자 문자열이어야 합니다.")
    if not isinstance(department, str) or not department.strip() or len(department) > 100:
        raise ValueError("department는 1~100자 문자열이어야 합니다.")
    if prepared_on is not None:
        try:
            dt.date.fromisoformat(str(prepared_on))
        except ValueError:
            raise ValueError("prepared_on은 YYYY-MM-DD 날짜여야 합니다.") from None
    spec = FORMS[form]
    marks = spec["marks"]
    evidence = [e for e in (evidence or []) if isinstance(e, dict)][:12]
    facts = [f for f in (facts or []) if isinstance(f, dict)][:20]
    commitments = [c for c in (commitments or []) if isinstance(c, dict)][:12]
    title = f"{topic} {spec['title_suffix']}"
    lines = [title, f"({prepared_on or CONFIRM}. {council} / {department})", ""]
    sections = []
    for index, (label, guide, fill) in enumerate(spec["sections"], 1):
        entries: list[dict] = []
        if fill == "evidence":
            for row in evidence:
                meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                head = " ".join(x for x in (format_meeting_date(meta.get("meeting_date")),
                                            str(meta.get("meeting_name") or "")) if x)
                question = row.get("question") if isinstance(row.get("question"), dict) else {}
                entries.append({"text": f"{head} {question.get('speaker') or ''}".strip()
                                        or str(row.get("docid") or ""),
                                "detail": str(question.get("text") or "")[:400] or None,
                                "source": "OFFICIAL_MINUTES", "citation": row.get("event_id") or row.get("docid")})
        elif fill == "facts":
            for fact in facts:
                entries.append({"text": _fact_line(fact), "detail": None,
                                "source": "USER_PROVIDED", "citation": fact.get("id")})
        elif fill == "commitments":
            seen_commitments: set[tuple] = set()
            for row in commitments:
                # 같은 답변이 여러 회의록 사본에 실리면 같은 문장이 반복된다. 문면이 같으면 한 번만 싣는다.
                mark = (row.get("commitment_type"), normalize(row.get("excerpt"))[:120],
                        normalize(row.get("deadline_verbatim")))
                if mark in seen_commitments:
                    continue
                seen_commitments.add(mark)
                cond = row.get("condition_verbatim")
                due = row.get("deadline_verbatim")
                tail = " / ".join(x for x in [f"조건 {cond}" if cond else "", f"기한 {due}" if due else "기한 미상"] if x)
                entries.append({"text": f"[{row.get('commitment_type') or '후속조치 후보'}] "
                                        + str(row.get("excerpt") or "")[:300],
                                "detail": tail or None, "source": "OFFICIAL_MINUTES",
                                "citation": row.get("event_id") or row.get("docid")})
        filled = bool(entries)
        sections.append({"order": index, "label": label, "display_label": pad_label(label),
                         "mark": marks[0], "guide": guide,
                         "content_source": {"evidence": "확인된 회의록 근거",
                                            "facts": "담당자 제공자료(USER_PROVIDED)",
                                            "commitments": "후속조치 후보",
                                            "blank": "담당자 작성"}[fill],
                         "entries": entries if filled else BLANK,
                         "status": "근거 배치" if filled else CONFIRM})
        lines.append(f"{index}. {pad_label(label)}")
        if filled:
            for entry in entries:
                lines.append(f"  {marks[1]} {entry['text']}")
                if entry.get("detail"):
                    lines.append(f"    {marks[2]} {entry['detail']}")
        else:
            lines.append(f"  {marks[1]} ({CONFIRM}) {guide}")
        lines.append("")
    lines.append(f"※ {NOTE}")
    return {"status": "PARTIAL", "workflow": "worksheet", "form": form, "title": title,
            "council": council, "department": department, "topic": topic,
            "prepared_on": prepared_on, "sections": sections,
            "plain_text": "\n".join(lines).rstrip() + "\n",
            "mark_convention": " → ".join(marks) + " / ※ 비고",
            "label_convention": "두 글자 항목명은 네 글자 폭으로 벌려 표기합니다(예: 개    요).",
            "manual_review": ["질의 취지에 직접 답했는지", "수치의 기준일·단위·회계연도가 일치하는지",
                              "검토되지 않은 사항을 확약하지 않았는지", "과거 답변과 현재 사실을 구분했는지"],
            "ready_for_submission": False, "stored": False,
            "limitations": [NOTE,
                            "서식 칸 배치만 수행하며 현황·검토의견 문장을 생성하지 않습니다.",
                            "기관마다 서식이 다를 수 있으므로 제출 전 소속 기관 양식과 대조하세요."]}
