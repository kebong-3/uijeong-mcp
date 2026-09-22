"""Request-language cues, not semantic verdicts, actor ratings or predictions.

Only verbatim local question sentences are scanned. Contrasting cues cause a
manual-review warning; the software never asserts requests have the same intent.
"""
from __future__ import annotations
import re

PATTERNS = {
    "DEFER_OR_STOP_CUE": re.compile(r"보류|중단|축소|하지\s*(?:말|않)|확대\s*(?:는|를|에)?\s*(?:반대|불가)"),
    "EXPAND_OR_START_CUE": re.compile(r"확대|확충|늘리|신설|도입|추진"),
    "VERIFY_OR_EXPLAIN_CUE": re.compile(r"확인|설명|검증|어떻게|얼마|언제|현황|실적"),
}


def request_cues(text: str, term: str | None = None) -> dict:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]
    local = [s for s in sentences if term and re.sub(r"\s+", "", term) in re.sub(r"\s+", "", s)] if term else sentences
    snippets = local[:3]  # Verbose quotes remain retrievable via event_id.
    cues = []
    for sentence in snippets:
        stop = bool(PATTERNS["DEFER_OR_STOP_CUE"].search(sentence))
        if stop:
            cues.append("DEFER_OR_STOP_CUE")
        # Do not count '확대는 보류' as a positive expansion cue.
        if not stop and PATTERNS["EXPAND_OR_START_CUE"].search(sentence):
            cues.append("EXPAND_OR_START_CUE")
        if PATTERNS["VERIFY_OR_EXPLAIN_CUE"].search(sentence):
            cues.append("VERIFY_OR_EXPLAIN_CUE")
    return {"cue_types": sorted(set(cues)) or ["UNDETERMINED"],
            "verbatim_context": snippets, "same_request_confirmed": False,
            "review_status": "MANUAL_CONTEXT_REVIEW_REQUIRED",
            "note": "문면상의 단서입니다. 인용·반어·복수 요구·조건을 자동 해석하지 않습니다."}
