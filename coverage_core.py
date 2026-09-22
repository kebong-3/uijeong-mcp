"""Keep retrieval completeness separate from the observed result count."""
from __future__ import annotations
from typing import Any, Iterable


def observed_status(count: int, *, upstream: str = "COMPLETE", incomplete: bool = False,
                    errors: Iterable[Any] = ()) -> str:
    if upstream in ("ERROR", "INVALID_INPUT"):
        return upstream
    if upstream == "PARTIAL" or incomplete or bool(list(errors)):
        return "PARTIAL"
    return "COMPLETE" if count else "EMPTY"


def summarize_coverage(coverage: list[dict], errors: list | None = None) -> dict:
    errors = errors or []
    incomplete = [c for c in coverage if c.get("exhausted") is not True or c.get("failed")]
    return {"scope": "이번 요청에 수집된 출처·검색조건", "is_exhaustive_council_review": False,
            "all_selected_sources_exhausted": bool(coverage) and not incomplete and not errors,
            "source_queries": len(coverage), "incomplete_source_queries": len(incomplete),
            "error_count": len(errors),
            "parsed_records_before_dedup": sum(int(c.get("parsed", 0) or 0) for c in coverage),
            "pending_refs": list(dict.fromkeys(ref for c in coverage for ref in c.get("pending_refs", []))),
            "note": "발견 0건은 자료의 전체 부재가 아닙니다. 오류·미열람 구간이 있으면 PARTIAL을 유지합니다."}


def combine_statuses(statuses: list[str], count: int, *, incomplete: bool = False) -> str:
    if "INVALID_INPUT" in statuses:
        return "INVALID_INPUT"
    if statuses and all(s == "ERROR" for s in statuses):
        return "ERROR"
    return observed_status(count, incomplete=incomplete or any(s in ("ERROR", "PARTIAL") for s in statuses))
