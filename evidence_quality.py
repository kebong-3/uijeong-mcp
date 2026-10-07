"""Pure, bounded output contracts for publicly retrieved administrative evidence.

Nothing in this module fetches evidence or certifies project identity, units,
legal applicability, organizational relationships or completeness.
"""
from __future__ import annotations

import copy
import json
from urllib.parse import urlsplit


def fiscal_unit_contract() -> dict:
    return {
        "unit_verified": False,
        "unit_source": "OFFICIAL_CATALOG_READ_UNIT_NOT_STATED",
        "unit_source_url": "https://www.data.go.kr/data/15138857/openapi.do",
        "unit_verified_at": None,
        "numeric_display_policy": "RAW_VALUE_ONLY",
        "numeric_normalization": "BLOCK_NUMERIC_NORMALIZATION",
        "unit_warning": "단위 미검증 원시값: 원·천원·백만원 환산 또는 확정액 합산 금지",
        "unit_field_coverage": {field: "NOT_VERIFIED" for field in (
            "bdg_cash_amt", "ep_amt", "cpl_amt", "bdg_ntep", "capep", "sggep", "etc_amt")},
    }


def _size(value) -> tuple[int, int]:
    raw = json.dumps(value, ensure_ascii=False, default=str)
    return len(raw), len(raw.encode("utf-8"))


def _thin_turn(turn: dict | None, chars: int = 500) -> dict | None:
    if not isinstance(turn, dict):
        return None
    out = {k: copy.deepcopy(turn[k]) for k in ("turn_index", "label", "role", "agenda", "act",
                "source_span", "department_context") if k in turn}
    text = str(turn.get("text") or "")
    out["text"] = text[:chars]
    citation = turn.get("citation") or {}
    out["citation"] = {k: copy.deepcopy(citation[k]) for k in (
        "record_id", "docid", "turn_index", "source_kind", "body_sha256", "turn_sha256",
        "source_url", "body_url", "char_start", "char_end", "locator") if k in citation}
    if len(text) > chars:
        out["excerpt"] = {"partial": True, "char_start": 0, "char_end": chars,
                          "original_chars": len(text), "basis": "ORIGINAL_TURN_TEXT"}
        out["citation"]["char_end"] = int(citation.get("char_start") or 0) + chars
    return out


def thin_event(event: dict) -> dict:
    out = {k: copy.deepcopy(event[k]) for k in ("event_id", "record_id", "docid", "kind",
            "source_kind", "matched_query", "evidence_state", "alternate_docids", "duplicate_reason",
            "linkage", "answer_link_status") if k in event}
    meta = event.get("metadata") or {}
    out["metadata"] = {k: copy.deepcopy(meta[k]) for k in (
        "council_id", "council_name", "term", "session", "sitting", "meeting_date", "meeting_name", "committee") if k in meta}
    for key in ("question", "speech"):
        if event.get(key):
            out[key] = _thin_turn(event[key])
    answers = event.get("answers") or []
    if answers:
        out["answers"] = [_thin_turn(a) for a in answers[:1]]
        out["answer_display"] = {"total": len(answers), "shown": min(1, len(answers))}
    out["retrieval"] = {"tool": "council_read_source", "arguments": {"ref": event.get("docid")},
                        "note": "전체 근거는 원래 snapshot의 동일 event_id로 회수하세요."}
    return out


def compact_bundle(result: dict) -> dict:
    """Keep actual items before generic response trimming can remove them.

    The snapshot already stores the complete collection. Trimming this response
    never changes the snapshot. Continuation counts actual displayed events.
    """
    initial_chars, initial_bytes = _size(result)
    if initial_chars <= 22000 and initial_bytes <= 60000:
        return result
    out = {k: copy.deepcopy(result[k]) for k in (
        "status", "snapshot_id", "parameters", "created_at", "item_offset", "total_items",
        "snapshot_scope", "coverage_summary", "limitations", "warnings") if k in result}
    rows = result.get("items") or []
    out["items"] = [thin_event(event) for event in rows[:5]]
    out["coverage"] = copy.deepcopy(result.get("coverage", []))
    out["errors"] = copy.deepcopy(result.get("errors", []))[:8]
    out["error_coverage"] = {"total": len(result.get("errors", [])), "shown": len(out["errors"])}
    records = result.get("records") or []
    out["records"] = [{"docid": r.get("docid"), "record_id": r.get("record_id"),
                       "metadata": {k: v for k, v in (r.get("metadata") or {}).items()
                                    if k in ("council_id", "meeting_date", "meeting_name", "session", "sitting")},
                       "body_sha256": r.get("body_sha256"), "alternate_docids": r.get("alternate_docids", [])}
                      for r in records[:30]]
    out["record_display"] = {"total": len(records), "shown": len(out["records"]),
                             "scope": "BOUND_INDEX_NOT_COMPLETE_ARCHIVE"}
    while len(out["items"]) > 3 and (_size(out)[0] > 22000 or _size(out)[1] > 60000):
        out["items"].pop()
    shown, offset = len(out["items"]), int(result.get("item_offset") or 0)
    next_offset = offset + shown if offset + shown < int(result.get("total_items") or 0) else None
    out["next_item_offset"] = next_offset
    out["status"] = "PARTIAL"
    out["continuation"] = ({"tool": "council_get_evidence", "arguments": {
        "snapshot_id": result.get("snapshot_id"), "item_offset": next_offset, "limit": 5}}
                           if next_offset is not None and result.get("snapshot_id") else None)
    out["display_budget"] = {"strategy": "THIN_INDEX_AND_SNAPSHOT", "original_chars": initial_chars,
                             "original_utf8_bytes": initial_bytes, "representative_items": shown,
                             "representatives_are_ranked": False, "full_snapshot_preserved": True,
                             "excerpt_recovery": "council_get_evidence(snapshot_id, item_offset)"}
    chars, nbytes = _size(out)
    out["display_budget"].update(response_chars=chars, response_utf8_bytes=nbytes)
    return out


def meeting_groups(rows: list[dict]) -> list[dict]:
    """Collapse complete matching *list metadata*, not claimed identical bodies."""
    from evidence_core import canonical_metadata, normalize_match
    groups, seen = [], {}
    for row in rows:
        meta = canonical_metadata(row)
        values = [meta.get(k) for k in ("council_id", "term", "session", "meeting_date", "meeting_name", "sitting")]
        key = tuple(normalize_match(str(v)) for v in values) if all(v is not None and str(v).strip() for v in values) else None
        if key is not None and key in seen:
            leader = seen[key]
            alternative = row.get("DOCID") or row.get("docid")
            if alternative and alternative != leader.get("DOCID") and alternative not in leader["alternate_docids"]:
                leader["alternate_docids"].append(alternative)
            continue
        leader = copy.deepcopy(row)
        leader["alternate_docids"] = list(leader.get("alternate_docids") or [])
        leader["meeting_group_basis"] = "COMPLETE_MEETING_LIST_METADATA" if key else "INCOMPLETE_METADATA_NOT_GROUPED"
        leader["body_equivalence_verified"] = False
        groups.append(leader)
        if key is not None:
            seen[key] = leader
    return groups


def integration_health(result: dict, last_checks: dict) -> dict:
    """Runtime health differs from coverage of optional live sample searches."""
    states = {}
    for name in ("CLIK", "finance365", "law", "public_data_search"):
        checked = last_checks.get(name) or last_checks.get(name.lower())
        if not checked:
            states[name] = {"state": "NO_CHECK_SINCE_RESTART", "query_status": None}
        else:
            status = str(checked.get("status", "UNKNOWN"))
            state = ("CHECK_FAILED" if status in ("ERROR", "TIMEOUT", "NOT_CONFIGURED", "UNAVAILABLE") else
                     "HEALTHY_BUT_SAMPLE_EMPTY" if status == "EMPTY" else
                     "HEALTHY_WITH_QUERY_WARNINGS" if status == "PARTIAL" else "HEALTHY")
            states[name] = {"state": state, "query_status": status, "checked_at": checked.get("checked_at")}
    for check in result.get("live_checks", []):
        if check.get("source") == "CLIK":
            states["CLIK"] = {"state": "CHECK_FAILED" if check.get("message") or check.get("code") else "HEALTHY"}
    manifest = result.get("release_verification", {}).get("status", "UNAVAILABLE")
    warnings = any(v["state"] != "HEALTHY" for v in states.values())
    return {"runtime_status": "HEALTHY" if manifest == "MATCH" else "VERIFICATION_REQUIRED",
            "deployment_status": manifest, "integration_status": states,
            "health_status": "HEALTHY_WITH_WARNINGS" if manifest == "MATCH" and warnings else
                             "HEALTHY" if manifest == "MATCH" else "VERIFICATION_REQUIRED",
            "health_scope": "응답 중인 프로세스·배포 일치·관측 조회만 점검. 미시험 연결을 정상 인증하지 않습니다."}


def final_quality_gate(context: dict) -> dict:
    """Automatic metadata check over actual returned layers, not a fact verifier."""
    finance = context.get("finance_context") or {}
    legal = context.get("legal_and_ordinance_context") or {}
    evidence = context.get("council_evidence") or context.get("evidence") or {}
    # context_pack uses council as a separate layer; source data is not invented.
    if not evidence:
        evidence = context.get("council_evidence_bundle") or {}
    budget_rows = list(finance.get("items") or [])
    ordinance_rows = list(legal.get("ordinances") or [])
    index = (context.get("linked_review") or {}).get("candidate_index") or {}
    budget_rows += list(index.get("budget") or [])
    ordinance_rows += list(index.get("ordinance") or [])
    issues = []
    for i, event in enumerate(evidence.get("items") or []):
        anchor = event.get("question") or event.get("speech") or {}
        citation = anchor.get("citation") or {}
        for key, value in (("meeting_date", (event.get("metadata") or {}).get("meeting_date")),
                           ("speaker", anchor.get("label")), ("docid", event.get("docid") or citation.get("docid"))):
            if not value:
                issues.append({"domain": "council", "index": i, "code": "MISSING_" + key.upper()})
        link = citation.get("source_url") or (event.get("provenance") or {}).get("source_url")
        if not link or '[REDACTED]' in link:
            issues.append({"domain": "council", "index": i, "code": "DIRECT_PUBLIC_URL_UNAVAILABLE",
                           "recovery": {"tool": "council_read_source", "arguments": {"ref": event.get("docid")}}})
    required = ["검색에서 발견된 후보와 실제 적용·동일사업 확인은 다릅니다."]
    for i, row in enumerate(budget_rows):
        if row.get("amount_unit") not in ("원", "천원", "백만원") or row.get("unit_verified") is not True:
            issues.append({"domain": "budget", "index": i, "code": "UNIT_NOT_VERIFIED",
                           "action": "BLOCK_NUMERIC_NORMALIZATION"})
        for key in ("fiscal_year", "execution_date", "project_code", "budget_stage"):
            if not row.get(key):
                issues.append({"domain": "budget", "index": i, "code": "MISSING_" + key.upper()})
    if any(r.get("code") == "UNIT_NOT_VERIFIED" for r in issues):
        required.append("단위 미검증 원시값이며 원·천원·백만원 환산 및 확정액 합산을 하지 않았습니다.")
    basis = finance.get("budget_basis") or {}
    if basis.get("requested_stage_supported") is False:
        required.append("요청한 본예산·추경·결산 확정액이 아니라 조회일 예산현액입니다.")
    for i, row in enumerate(ordinance_rows):
        for key in ("title", "jurisdiction", "document_id", "mst"):
            if not row.get(key):
                issues.append({"domain": "ordinance", "index": i, "code": "MISSING_" + key.upper()})
        if not (row.get("effective_date") or row.get("enforcement_date")):
            issues.append({"domain": "ordinance", "index": i, "code": "EFFECTIVE_DATE_REQUIRES_DOCUMENT"})
    if context.get("status") == "PARTIAL":
        required.append("이번 검색범위에서 일부만 확인했으며 미조회 자료의 부재를 단정하지 않습니다.")
    def identities(rows, keys):
        found, seen = [], set()
        for row in rows:
            item = {k: row[k] for k in keys if k in row}
            token = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if token not in seen:
                found.append(item); seen.add(token)
        return found
    entity = {"canonical_name": context.get("topic", ""), "jurisdiction": context.get("council", ""),
              "name_status": "USER_TOPIC_NOT_CERTIFIED_CANONICAL_PROJECT", "aliases": [],
              "project_codes": identities(budget_rows, ("project_code", "local_government_code", "fiscal_year", "execution_date", "account")),
              "ordinance_refs": identities(ordinance_rows, ("document_id", "mst", "title", "jurisdiction")),
              "council_snapshot_id": evidence.get("snapshot_id"),
              "relationship_state": "CO_RETRIEVED_CANDIDATES", "same_project_verified": False,
              "legal_applicability_verified": False}
    return {"status": "METADATA_REVIEW_ONLY", "verified_facts": False, "legal_approval": False,
            "numeric_normalization": "BLOCK_NUMERIC_NORMALIZATION" if any(i.get("code") == "UNIT_NOT_VERIFIED" for i in issues) else "NOT_CERTIFIED_BY_THIS_GATE",
            "issues": issues[:20], "total_issues": len(issues), "required_answer_qualifiers": required,
            "policy_entity": entity, "ready_for_submission": False}
