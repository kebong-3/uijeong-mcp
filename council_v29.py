"""v2.9 evidence-complete workflow extensions for 지방의회MCP.

Adds:
- council_peer_cases: bounded nationwide examples with actual Q&A evidence
- council_department_session_brief: department-first pre-session preparation

Design:
- No politician scoring, ranking, profiling or outcome prediction.
- Peer cases are examples found within a bounded search, not "best" cases.
- Every result carries a coverage card and MCP execution trace.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

import evidence_core as E
import runtime_security as R
from result_contract import wire_result

_TERMS_PATH = Path(__file__).parent / "data" / "administrative_terms.json"
try:
    _TERM_MAP = json.loads(_TERMS_PATH.read_text(encoding="utf-8")).get("terms", {})
except (OSError, ValueError, TypeError):
    _TERM_MAP = {}


def _norm(value: str) -> str:
    return E.normalize_match(value or "")


def _expansions(topic: str, limit: int = 2) -> list[str]:
    q = _norm(topic)
    out: list[str] = []
    for key, values in _TERM_MAP.items():
        k = _norm(key)
        if not k or not (k in q or q in k):
            continue
        for value in values:
            if value and value != topic and value not in out:
                out.append(value)
                if len(out) >= limit:
                    return out
    return out


def _date_yyyymmdd(value: Any) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    return text[:8] if len(text) >= 8 else ""


def _minus_years(day: dt.date, years: int) -> dt.date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, month=2, day=28)


def _event_excerpt(event: dict[str, Any]) -> dict[str, Any]:
    question = event.get("question") or {}
    answers = event.get("answers") or []
    return {
        "question": {
            "label": question.get("label"),
            "text": (question.get("text") or "")[:1600],
            "citation": question.get("citation"),
        } if question else None,
        "answers": [{
            "label": item.get("label"),
            "text": (item.get("text") or "")[:1600],
            "citation": item.get("citation"),
        } for item in answers[:4]],
        "kind": event.get("kind"),
        "coverage_note": event.get("coverage_note"),
    }


def _coverage_status(*, errors: list[dict[str, Any]], returned: int, requested: int) -> str:
    if errors and not returned:
        return "ERROR"
    if returned == 0:
        return "EMPTY" if not errors else "ERROR"
    if errors or returned < requested:
        return "PARTIAL"
    return "COMPLETE"


async def _peer_cases(
    U: Any,
    topic: str,
    *,
    years: int = 5,
    case_count: int = 3,
    search_terms: Optional[list[str]] = None,
    max_details: int = 12,
) -> dict[str, Any]:
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
        return {"status": "INVALID_INPUT", "message": "topic은 1~200자 문자열이어야 합니다."}
    if type(years) is not int or not 1 <= years <= 10:
        return {"status": "INVALID_INPUT", "message": "years는 1~10 정수입니다."}
    if type(case_count) is not int or not 1 <= case_count <= 5:
        return {"status": "INVALID_INPUT", "message": "case_count는 1~5 정수입니다."}
    if type(max_details) is not int or not 3 <= max_details <= 15:
        return {"status": "INVALID_INPUT", "message": "max_details는 3~15 정수입니다."}
    if search_terms is not None and (
        not isinstance(search_terms, list)
        or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in search_terms)
    ):
        return {"status": "INVALID_INPUT", "message": "search_terms는 1~100자 문자열 목록입니다."}

    terms = [topic.strip()]
    for value in (search_terms or []) + _expansions(topic, 2):
        value = value.strip()
        if value not in terms:
            terms.append(value)
        if len(terms) >= 3:
            break

    today = dt.date.today()
    date_to = today.strftime("%Y%m%d")
    date_from = _minus_years(today, years).strftime("%Y%m%d")
    errors: list[dict[str, Any]] = []
    list_candidates: dict[str, dict[str, Any]] = {}
    list_calls = []

    # Global CLIK search: bounded metadata search, no per-council fan-out.
    for term in terms:
        try:
            obj = await U.clik.get(
                "minutes.do",
                displayType="list",
                startCount=0,
                listCount=100,
                searchType="MINTS_HTML",
                searchKeyword=term,
                sort="MTG_DE/DESC",
            )
            rows = U._rows(obj)
            accepted = 0
            for row in rows:
                docid = str(row.get("DOCID") or "")
                meeting_date = _date_yyyymmdd(row.get("MTG_DE"))
                if not docid or not meeting_date or not (date_from <= meeting_date <= date_to):
                    continue
                if docid not in list_candidates:
                    list_candidates[docid] = dict(row, _matched_terms=[term])
                elif term not in list_candidates[docid]["_matched_terms"]:
                    list_candidates[docid]["_matched_terms"].append(term)
                accepted += 1
            list_calls.append({
                "term": term,
                "upstream_total": int(obj.get("TOTAL_COUNT") or 0),
                "rows_received": len(rows),
                "rows_in_period": accepted,
            })
        except Exception as exc:
            errors.append({"source": "CLIK", "stage": "nationwide_list", "term": term,
                           "message": R.safe_error(exc)})

    candidates = sorted(
        list_candidates.values(),
        key=lambda row: (_date_yyyymmdd(row.get("MTG_DE")), str(row.get("DOCID") or "")),
        reverse=True,
    )

    cases = []
    seen_councils = set()
    details_checked = 0
    details_with_qa = 0
    for row in candidates:
        if len(cases) >= case_count or details_checked >= max_details:
            break
        council_name = str(row.get("RASMBLY_NM") or "").strip()
        if not council_name or council_name in seen_councils:
            continue
        docid = str(row.get("DOCID") or "")
        details_checked += 1
        try:
            detail = await U.minutes_detail(docid)
            turns = await asyncio.to_thread(E.parse_turns, detail.get("MINTS_HTML", "") or "")
            meta = {**row, **detail}
            record = E.make_record(
                meta, turns, source="CLIK", source_kind="PUBLIC_API",
                source_url=detail.get("ORGINL_FILE_URL") or row.get("ORGINL_FILE_URL"),
                source_url_verified=False,
            )
            events = []
            for term in row.get("_matched_terms", terms):
                events.extend(E.record_events(record, term, "질의답변", None))
            # De-duplicate by event_id and require a real question event.
            unique = {event.get("event_id"): event for event in events if event.get("question")}
            events = list(unique.values())
            if not events:
                continue
            details_with_qa += 1
            event = events[0]
            meta2 = record.get("metadata", {})
            source_url = record.get("provenance", {}).get("source_url")
            cases.append({
                "council_name": meta2.get("council_name") or council_name,
                "council_id": meta2.get("council_id") or row.get("RASMBLY_ID"),
                "meeting_date": meta2.get("meeting_date"),
                "meeting_name": meta2.get("meeting_name"),
                "committee": meta2.get("committee"),
                "agenda_title": meta2.get("agenda_title"),
                "docid": docid,
                "matched_terms": row.get("_matched_terms", []),
                "evidence": _event_excerpt(event),
                "source_url": source_url,
                "source_url_status": record.get("provenance", {}).get("source_url_status"),
                "selection_basis": "최근 검색결과에서 실제 질의 발언이 확인된 서로 다른 의회 사례",
            })
            seen_councils.add(council_name)
        except Exception as exc:
            errors.append({"source": "CLIK", "stage": "detail_or_parse", "docid": docid,
                           "message": R.safe_error(exc)})

    status = _coverage_status(errors=errors, returned=len(cases), requested=case_count)
    limited = details_checked >= max_details or any(x["upstream_total"] > x["rows_received"] for x in list_calls)
    if limited and len(cases) < case_count and status == "EMPTY":
        status = "PARTIAL"
    return {
        "status": status,
        "workflow": "PEER_COUNCIL_CASES",
        "topic": topic.strip(),
        "cases": cases,
        "coverage_card": {
            "date_from": date_from,
            "date_to": date_to,
            "search_terms": terms,
            "list_calls": list_calls,
            "unique_list_candidates": len(candidates),
            "details_checked": details_checked,
            "details_with_actual_question": details_with_qa,
            "distinct_councils_returned": len(cases),
            "requested_case_count": case_count,
            "max_details": max_details,
            "limited": limited,
            "is_exhaustive_national_archive": False,
            "clik_coverage_note": "CLIK Open API 연계 범위와 상세확인 상한 내 사례 검색이며 전국 모든 의회의 전수 결과가 아닙니다.",
        },
        "errors": errors,
        "execution_trace": {
            "mcp_tool": "council_peer_cases",
            "mcp_first": True,
            "source": "CLIK minutes",
            "supplemental_web_search_policy": "공식 원문 링크가 없거나 CLIK 미연계 가능성이 있을 때만 해당 의회 공식 홈페이지 검색으로 보완",
        },
        "interpretation": [
            "반환 순서는 우수성·대표성 순위가 아니라 최근 검색결과 기준입니다.",
            "의원 개인의 성향·관심도·성과를 평가하지 않습니다.",
            "미발견은 확인 범위의 미발견이며 전국에 사례가 없다는 뜻이 아닙니다.",
        ],
    }


async def _department_session_brief(
    U: Any,
    department: str,
    *,
    council: str = "광주 서구",
    purpose: str = "행정사무감사",
    years: int = 3,
    committee: Optional[str] = None,
    max_docs_per_year: int = 4,
) -> dict[str, Any]:
    if not isinstance(department, str) or not department.strip() or len(department) > 100:
        return {"status": "INVALID_INPUT", "message": "department는 1~100자 부서명입니다."}
    if purpose not in {"행정사무감사", "업무보고", "본예산", "추경", "일반"}:
        return {"status": "INVALID_INPUT", "message": "purpose는 행정사무감사|업무보고|본예산|추경|일반입니다."}
    if type(years) is not int or not 1 <= years <= 5:
        return {"status": "INVALID_INPUT", "message": "years는 1~5 정수입니다."}

    today = dt.date.today()
    date_to = today.strftime("%Y-%m-%d")
    date_from = _minus_years(today, years).strftime("%Y-%m-%d")

    brief_task = U.council_department_brief(
        department=department, council=council, date_from=date_from, date_to=date_to,
        committee=committee, max_docs=min(6, max_docs_per_year + 2), limit=20, source="auto",
    )
    recurring_task = U.council_recurring_issues(
        department=department, council=council, years=years, include_current_year=True,
        committee=committee, min_years=2 if years >= 2 else 1,
        top=12, max_docs_per_year=max_docs_per_year,
        period_mode="rolling_years", source="auto",
    ) if years >= 2 else None

    if recurring_task is None:
        brief = await brief_task
        recurring = {"status": "SKIPPED", "recurring": []}
    else:
        brief, recurring = await asyncio.gather(brief_task, recurring_task)

    statuses = [brief.get("status"), recurring.get("status")]
    errors = []
    errors.extend(brief.get("errors", []) if isinstance(brief, dict) else [])
    errors.extend(recurring.get("errors", []) if isinstance(recurring, dict) else [])
    recurring_items = recurring.get("recurring", []) if isinstance(recurring, dict) else []

    status = "COMPLETE"
    if any(x == "ERROR" for x in statuses):
        status = "PARTIAL" if any(x in ("COMPLETE", "PARTIAL") for x in statuses) else "ERROR"
    elif any(x == "PARTIAL" for x in statuses):
        status = "PARTIAL"
    elif all(x in ("EMPTY", "SKIPPED") for x in statuses):
        status = "EMPTY"

    checklist = [
        {"item": "최근 의회 질의·답변", "status": brief.get("status"),
         "action": "주요 질의의 현재 사실관계와 최신 수치 확인"},
        {"item": "반복 쟁점 후보", "status": recurring.get("status"),
         "action": "같은 요구인지 원문 대조 후 현재 조치상태 확인"},
        {"item": "과거 집행부 답변의 후속조치", "status": "DEPARTMENT_CONFIRMATION_REQUIRED",
         "action": "실제 이행 여부와 증빙자료 확인"},
        {"item": "현재 사업실적·민원·만족도", "status": "DEPARTMENT_CONFIRMATION_REQUIRED",
         "action": "최신 내부자료 준비"},
        {"item": "예산·추경·결산 수치", "status": "DEPARTMENT_CONFIRMATION_REQUIRED" if purpose in {"행정사무감사","본예산","추경"} else "AS_NEEDED",
         "action": "핵심 쟁점별 council_finance_context와 공식 예산서 대조"},
        {"item": "법령·조례 근거", "status": "AS_NEEDED",
         "action": "핵심 쟁점별 council_legislation_context 확인"},
    ]

    return {
        "status": status,
        "workflow": "DEPARTMENT_SESSION_BRIEF",
        "department": department.strip(),
        "council": council,
        "purpose": purpose,
        "period": {"date_from": date_from, "date_to": date_to, "years": years},
        "department_brief": brief,
        "recurring_issues": recurring,
        "focus_topic_candidates": recurring_items[:8],
        "readiness_checklist": checklist,
        "coverage_card": {
            "department_brief_status": brief.get("status"),
            "recurring_status": recurring.get("status"),
            "errors": len(errors),
            "is_prediction": False,
            "interpretation": "반복 쟁점은 과거 공개기록에서 반복 등장한 주제 후보이며 향후 의원 질문을 예측한 결과가 아닙니다.",
        },
        "execution_trace": {
            "mcp_tool": "council_department_session_brief",
            "mcp_first": True,
            "stages": ["council_department_brief", "council_recurring_issues"],
        },
        "recommended_next_step": "focus_topic_candidates 중 실제 회기 준비가 필요한 주제를 골라 council_session_ready_pack으로 법령·재정까지 연결하세요.",
    }


def install(U: Any) -> None:
    async def council_peer_cases(
        topic: str,
        years: int = 5,
        case_count: int = 3,
        search_terms: Optional[list[str]] = None,
        max_details: int = 12,
    ) -> dict[str, Any]:
        """전국 CLIK에서 동일·유사 주제의 실제 의원 질의가 확인된 서로 다른 지방의회 사례를 제한적으로 찾습니다.
        반환 순서는 순위가 아니며 전국 전수조사도 아닙니다."""
        return await _peer_cases(
            U, topic, years=years, case_count=case_count,
            search_terms=search_terms, max_details=max_details,
        )

    async def council_department_session_brief(
        department: str,
        council: str = "광주 서구",
        purpose: str = "행정사무감사",
        years: int = 3,
        committee: Optional[str] = None,
        max_docs_per_year: int = 4,
    ) -> dict[str, Any]:
        """주제어를 아직 정하지 못한 부서가 회기 전에 최근 질의와 반복쟁점 후보부터 점검하는 부서 기준 진입점입니다."""
        return await _department_session_brief(
            U, department, council=council, purpose=purpose, years=years,
            committee=committee, max_docs_per_year=max_docs_per_year,
        )

    for fn in (council_peer_cases, council_department_session_brief):
        setattr(U, fn.__name__, fn)
        if U.profile_allows(fn.__name__):
            try:
                U.mcp.remove_tool(fn.__name__)
            except Exception:
                pass
            U.mcp.tool(name=fn.__name__, annotations=U.RO)(wire_result(fn))
