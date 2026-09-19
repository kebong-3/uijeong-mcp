"""Bound tool responses without losing evidence.

An MCP tool result is consumed inside a model context window. An unbounded
result is not "more complete" — past the window it is unusable, and the client
either truncates it blindly or fails. This module enforces a character budget
and records every reduction, so a shortened answer still states what was left
out and how to fetch it.

Reductions are applied in order of least evidentiary loss:
  1. cap bulk arrays (per-path caps, then progressively tighter)
  2. shorten long verbatim bodies into a quote window, keeping char offsets
  3. drop remaining bulk arrays as a last resort

Nothing is removed silently. Every step appends to ``response_budget.reduced``
with the path, the original count and the retrieval route.
"""
from __future__ import annotations

import json
import copy
import hashlib
import os
from typing import Any

DEFAULT_MAX_CHARS = 30_000          # ≈1.5만 토큰: 한 대화에서 여러 번 호출해도 버틴다
MIN_MAX_CHARS = 8_000
HARD_MAX_CHARS = 200_000
# 이 크기 이하의 결과는 MCP 권고대로 텍스트 블록에 직렬화 JSON을 함께 담는다.
DEFAULT_TEXT_JSON_MAX = 8_000

# Arrays that grow with the size of the source material, with a default cap and
# the route a caller uses to read the rest. Paths match the trailing key name.
BULK_ARRAYS: dict[str, tuple[int, str]] = {
    "items": (10, "같은 snapshot_id로 item_offset을 늘려 이어봅니다."),
    "discussion_evidence": (12, "council_evidence_bundle(mode='질의답변')에서 item_offset으로 이어봅니다."),
    "other_speech_evidence": (8, "council_evidence_bundle(mode='발언')으로 조회합니다."),
    "followup_candidates": (12, "council_prepare_pack의 followup_ledger 또는 mode='약속' bundle에서 확인합니다."),
    "entries": (12, "council_evidence_bundle(mode='약속')에서 item_offset으로 이어봅니다."),
    "preparation_questions": (8, "question_candidates 절에서 확인합니다."),
    "candidates": (8, "council_evidence_bundle(mode='질의답변') 결과로 직접 확인합니다."),
    "question_occurrences": (4, "해당 질문의 docid 또는 site:key로 council_read_source를 엽니다."),
    "source_answers": (2, "docid 또는 site:key와 turn_index로 council_read_source를 엽니다."),
    "answers": (2, "docid 또는 site:key와 turn_index로 council_read_source를 엽니다."),
    "turns": (20, "start_turn을 늘려 이어읽습니다."),
    "sources": (12, "council_data_sources의 offset으로 이어봅니다."),
    "links": (20, "limit을 조정해 다시 조회합니다."),
    "errors": (10, "동일 조건으로 다시 조회해 재현 여부를 확인합니다."),
    "pending_refs": (10, "각 ref를 council_read_source로 직접 엽니다."),
    "years": (6, "years 인자를 줄여 연도별로 조회합니다."),
}

# Long verbatim strings: key -> (kept chars, retrieval route).
LONG_TEXT: dict[str, tuple[int, str]] = {
    "text": (700, "council_read_source로 원문 전체를 확인합니다."),
    "excerpt": (700, "council_read_source로 원문 전체를 확인합니다."),
    "quote": (700, "council_read_source로 원문 전체를 확인합니다."),
    "speech": (700, "council_read_source로 원문 전체를 확인합니다."),
    "candidate_excerpt": (500, "council_read_source로 원문 전체를 확인합니다."),
    "candidate_citation": (500, "council_read_source로 원문 전체를 확인합니다."),
    "body": (900, "council_read_source로 원문 전체를 확인합니다."),
    "content": (900, "council_read_source로 원문 전체를 확인합니다."),
}

_NEVER_TRIM = frozenset({
    "status", "snapshot_id", "record_id", "event_id", "entry_id", "docid", "ref",
    "council_id", "source_kind", "body_hash", "turn_hash", "quote_sha256",
    "turn_index", "char_start", "char_end", "next_start_turn", "next_start_char",
    "next_offset", "next_page", "next_item_offset", "item_offset", "source_url",
    "body_url", "fiscal_year", "fulfillment_status", "message",
})


def max_chars() -> int:
    """Response budget in characters. ``UIJEONG_MAX_RESPONSE_CHARS`` overrides."""
    raw = os.environ.get("UIJEONG_MAX_RESPONSE_CHARS", "").strip()
    if not raw:
        return DEFAULT_MAX_CHARS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CHARS
    return min(HARD_MAX_CHARS, max(MIN_MAX_CHARS, value))


def text_json_max_chars() -> int:
    """Below this size the text block repeats the JSON (client compatibility)."""
    raw = os.environ.get("UIJEONG_TEXT_JSON_MAX_CHARS", "").strip()
    if not raw:
        return DEFAULT_TEXT_JSON_MAX
    try:
        return min(HARD_MAX_CHARS, max(0, int(raw)))
    except ValueError:
        return DEFAULT_TEXT_JSON_MAX


def size_of(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def _cap_arrays(node: Any, scale: float, log: list[dict], path: str = "") -> Any:
    """Return a copy with bulk arrays capped. ``scale`` shrinks every cap."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, list) and key in BULK_ARRAYS and value:
                cap_default, route = BULK_ARRAYS[key]
                cap = max(1, int(cap_default * scale)) if scale < 1 else cap_default
                if len(value) > cap:
                    log.append({"path": here, "kind": "array", "original": len(value),
                                "kept": cap, "omitted": len(value) - cap, "retrieval": route})
                    out[key] = [_cap_arrays(v, scale, log, f"{here}[]") for v in value[:cap]]
                    out[f"{key}_omitted"] = {"count": len(value) - cap, "total": len(value),
                                             "retrieval": route}
                    continue
            out[key] = _cap_arrays(value, scale, log, here)
        return out
    if isinstance(node, list):
        return [_cap_arrays(v, scale, log, f"{path}[]") for v in node]
    return node


def _trim_text(node: Any, scale: float, log: list[dict], path: str = "") -> Any:
    """Shorten long verbatim strings, keeping a stated quote window."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, str) and key in LONG_TEXT and key not in _NEVER_TRIM:
                keep_default, route = LONG_TEXT[key]
                keep = max(120, int(keep_default * scale))
                if len(value) > keep:
                    log.append({"path": here, "kind": "text", "original": len(value),
                                "kept": keep, "omitted": len(value) - keep, "retrieval": route})
                    out[key] = value[:keep] + "…"
                    out[f"{key}_truncated"] = {"kept_chars": keep, "original_chars": len(value),
                                               "retrieval": route,
                                               "note": "원문 표현을 자른 것이며 문구를 고치지 않았습니다."}
                    continue
            out[key] = _trim_text(value, scale, log, here)
        return out
    if isinstance(node, list):
        return [_trim_text(v, scale, log, f"{path}[]") for v in node]
    return node


def _drop_arrays(node: Any, log: list[dict], path: str = "") -> Any:
    """Last resort: replace bulk arrays with a stated omission record."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, list) and key in BULK_ARRAYS and len(value) > 1:
                route = BULK_ARRAYS[key][1]
                log.append({"path": here, "kind": "array_dropped", "original": len(value),
                            "kept": 1, "omitted": len(value) - 1, "retrieval": route})
                out[key] = [value[0]]
                out[f"{key}_omitted"] = {"count": len(value) - 1, "total": len(value), "retrieval": route}
                continue
            out[key] = _drop_arrays(value, log, here)
        return out
    if isinstance(node, list):
        return [_drop_arrays(v, log, f"{path}[]") for v in node]
    return node


def _trim_all_strings(node: Any, keep: int, log: list[dict], path: str = "") -> Any:
    """Generic clamp for any remaining long string, including unknown keys."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if isinstance(value, str) and len(value) > keep and key not in _NEVER_TRIM:
                log.append({"path": here, "kind": "text", "original": len(value), "kept": keep,
                            "omitted": len(value) - keep,
                            "retrieval": "council_read_source로 원문을 확인합니다."})
                out[key] = value[:keep] + "…"
                continue
            out[key] = _trim_all_strings(value, keep, log, here)
        return out
    if isinstance(node, list):
        return [_trim_all_strings(v, keep, log, f"{path}[]") for v in node]
    return node


_ESSENTIAL = ("status", "message", "snapshot_id", "keyword", "council", "topic",
              "requested_council", "mode", "total_items", "next_item_offset", "ref",
              "source_url", "limitations", "reason", "recovery", "item_offset", "collection",
              "next_start_turn", "next_start_char", "offset", "next_offset")


def _minimal(payload: dict, cap: int, log: list[dict]) -> dict:
    """Last line of defence: keep identifiers and the route to the evidence."""
    kept = {k: payload[k] for k in _ESSENTIAL if k in payload}
    kept["items"] = []
    kept["budget_fallback"] = {
        "reason": "축약 후에도 응답 한도를 넘어 본문을 싣지 못했습니다.",
        "retrieval": "max_docs·limit·max_evidence를 줄여 다시 조회하거나, snapshot_id와 "
                     "item_offset으로 나눠 받고 원문은 council_read_source로 확인하세요.",
        "cap_chars": cap,
    }
    if str(kept.get("status")) in ("COMPLETE", "PARTIAL", "EMPTY"):
        kept["status"] = "PARTIAL"
    log.append({"path": "(root)", "kind": "envelope_reduced", "original": size_of(payload),
                "kept": size_of(kept), "omitted": max(0, size_of(payload) - size_of(kept)),
                "retrieval": kept["budget_fallback"]["retrieval"]})
    return kept


def _repair(original: Any, bounded: Any) -> Any:
    """Move continuations to the first undisplayed item or character, never past it."""
    if isinstance(original, list) and isinstance(bounded, list):
        return [_repair(o,b) for o,b in zip(original,bounded)]
    if not isinstance(original,dict) or not isinstance(bounded,dict):return bounded
    out={k:_repair(original.get(k),v) for k,v in bounded.items()}
    # Quote hashes and source spans refer to original material, not the displayed prefix.
    for key in LONG_TEXT:
        old,new=original.get(key),out.get(key)
        if isinstance(old,str) and isinstance(new,str) and old!=new:
            prefix=new[:-1] if new.endswith('…') else new
            if old.startswith(prefix):
                out[key+'_display']={'char_start':0,'char_end':len(prefix),'original_chars':len(old),
                    'sha256':hashlib.sha256(prefix.encode()).hexdigest(),'source_locator_unchanged':True}
    for name,start_key,next_key in [('items','item_offset','next_item_offset'),('sources','offset','next_offset')]:
        old,new=original.get(name),out.get(name)
        if isinstance(old,list) and isinstance(new,list) and len(new)<len(old) and start_key in original:
            out[next_key]=original[start_key]+len(new)
            out['status']='PARTIAL'
            out['continuation_note']='다음 위치는 실제 표시한 마지막 항목 뒤입니다.'
    old,new=original.get('turns'),out.get('turns')
    if isinstance(old,list) and old and new is None:
        out['next_start_turn']=old[0]['idx'];out['next_start_char']=old[0].get('source_char_start',0)
        out['status']='PARTIAL'
    if isinstance(old,list) and isinstance(new,list):
        for i,turn in enumerate(new):
            prior=old[i]
            body=turn.get('text','');source=prior.get('text','')
            if body!=source:
                prefix=body[:-1] if body.endswith('…') else body
                if source.startswith(prefix):
                    turn['text']=prefix
                    base=prior.get('source_char_start',0)
                    turn['source_char_end']=base+len(prefix)
                    turn['is_fragment']=True
                    out['turns']=new[:i+1]
                    out['next_start_turn']=turn['idx'];out['next_start_char']=base+len(prefix)
                    out['status']='PARTIAL'
                    break
        else:
            if len(new)<len(old):
                first=old[len(new)]
                out['next_start_turn']=first['idx'];out['next_start_char']=first.get('source_char_start',0)
                out['status']='PARTIAL'
        if 'coverage' in out and isinstance(out['coverage'],dict):
            out['coverage']={**out['coverage'],'returned_pieces':len(out['turns']),
                'returned_chars':sum(len(t.get('text','')) for t in out['turns']),
                'complete_selected_range':out.get('next_start_turn') is None}
    return out


def apply_budget(payload: Any, limit: int | None = None) -> Any:
    """Return ``payload`` reduced to fit the budget, with a report attached.

    A dict gains a ``response_budget`` block. Short results are returned
    unchanged apart from that block, so callers see the budget was checked.
    """
    if not isinstance(payload, (dict, list)):
        return payload
    cap = limit if isinstance(limit, int) and limit > 0 else max_chars()
    original = size_of(payload)
    log: list[dict] = []
    result = payload
    if original > cap:
        for scale in (1.0, 0.6, 0.35, 0.2):
            log = []
            result = _trim_text(_cap_arrays(payload, scale, log, ""), scale, log, "")
            if size_of(_repair(payload,result)) <= cap-min(cap//5,1800):
                break
        if size_of(result) > cap:
            result = _drop_arrays(result, log, "")
        for keep in (400, 200, 100):
            if size_of(result) <= cap:
                break
            result = _trim_all_strings(result, keep, log, "")
        if size_of(result) > cap and isinstance(result, dict):
            result = _minimal(result, cap, log)
    if not isinstance(result, dict):
        return result

    def envelope(node: dict, entries: int) -> dict:
        report = {"max_chars": cap, "original_chars": original, "response_chars": size_of(node),
                  "truncated": bool(log)}
        if log:
            report["reduced"] = log[:entries]
            report["reduced_count"] = len(log)
            if len(log) > entries:
                report["reduced_listed"] = entries
            report["note"] = ("응답 한도를 지키기 위해 목록·인용을 축약했습니다. 생략된 항목은 "
                              "존재하지 않는 것이 아니며 각 retrieval 경로로 확인합니다.")
            if str(node.get("status")) == "COMPLETE":
                node = {**node, "status": "PARTIAL"}
                report["status_downgraded"] = "COMPLETE→PARTIAL: 축약된 항목이 있어 부분 결과로 표시"
        return {**node, "response_budget": report}

    # 보고 블록도 응답에 실리므로 최종 객체 크기로 판정한다.
    for entries in (40, 12, 4, 0):
        final = envelope(_repair(payload,result), entries)
        if size_of(final) <= cap:
            return final
    final=envelope(_repair(payload,_minimal(payload,cap,log)),0)
    if size_of(final)<=cap:return final
    # Oversized protected fields cannot be preserved verbatim under a hard cap.
    essential={k:v for k,v in final.items() if k in ('status','snapshot_id','ref','item_offset','collection','next_item_offset','next_start_turn','next_start_char') and size_of(v)<500}
    if essential.get('status') not in ('ERROR','INVALID_INPUT'):essential['status']='PARTIAL'
    essential['message']='응답 한도 초과: 본문 미표시. 같은 조회를 작은 limit/max_chars로 다시 요청하세요.'
    essential['response_budget']={'max_chars':cap,'truncated':True,'reduced':[{'path':'(root)','kind':'oversized_envelope'}]}
    if size_of(essential)>cap:
        return {'status':'PARTIAL','message':'응답 한도 초과'}
    return essential


# ── 텍스트 요약(모델이 먼저 읽는 본문) ──────────────────────────────────────
_DIGEST_MAX = 2_400


def _coverage_line(coverage: Any) -> list[str]:
    rows = coverage if isinstance(coverage, list) else [coverage] if isinstance(coverage, dict) else []
    out = []
    for c in rows[:4]:
        if not isinstance(c, dict):
            continue
        parts = [str(c.get("source") or c.get("council_id") or "출처")]
        for key, label in (("scanned", "검토"), ("selected", "선정"), ("parsed", "해석"),
                           ("upstream_total", "상류목록")):
            if isinstance(c.get(key), int):
                parts.append(f"{label} {c[key]:,}")
        for key, label in (("next_offset", "다음 source_offset"), ("next_page", "다음 site_start_page")):
            if c.get(key) not in (None, False):
                parts.append(f"{label}={c[key]}")
        if c.get("failed"):
            parts.append("조회 실패")
        out.append("  · " + " / ".join(parts))
    return out


def digest(payload: dict) -> str:
    """One screen of text: status, scope, a few citations, what to read next.

    The full data stays in ``structuredContent``; this is what the model reads
    first, so it names the limits rather than burying them.
    """
    status = str(payload.get("status", ""))
    lines = [f"상태: {status}" if status else "상태: 미표기"]
    if payload.get("message"):
        lines.append(str(payload["message"])[:400])
    label = {"COMPLETE": "이번 요청 범위 확인 완료(기관 전체 전수 아님)",
             "PARTIAL": "일부 확인 — 이어보기 위치와 생략분을 함께 확인",
             "EMPTY": "확인한 범위에 결과 없음(전체 부재 아님)",
             "ERROR": "조회·처리 실패 — 자료 부재로 해석 금지",
             "INVALID_INPUT": "입력 오류 — 조건을 고쳐 다시 조회"}.get(status)
    if label:
        lines.append(label)
    for key, name in (("topic", "주제"), ("requested_council", "대상"), ("council", "대상"),
                      ("keyword", "검색어"), ("mode", "모드")):
        if payload.get(key):
            lines.append(f"{name}: {payload[key]}")
            break
    if payload.get("snapshot_id"):
        lines.append(f"snapshot_id: {payload['snapshot_id']}")
    counts = []
    for key in ("items", "entries", "candidates", "sources", "links", "turns", "years"):
        value = payload.get(key)
        if isinstance(value, list):
            counts.append(f"{key} {len(value)}건")
    for section in ("briefing", "question_candidates", "followup_ledger"):
        node = payload.get(section)
        if isinstance(node, dict):
            inner = [f"{k} {len(v)}" for k, v in node.items() if isinstance(v, list) and v]
            if inner:
                counts.append(f"{section}({', '.join(inner[:3])})")
    if counts:
        lines.append("내용: " + " · ".join(counts))
    cov = _coverage_line(payload.get("coverage"))
    if cov:
        lines.append("확인 범위:")
        lines.extend(cov)
    rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    if rows:
        lines.append("주요 근거:")
        for row in rows[:3]:
            if not isinstance(row, dict):
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            head = " ".join(str(meta.get(k)) for k in ("meeting_date", "council_name", "meeting_name")
                            if meta.get(k))
            quoted = ""
            for holder in ("question", "speech"):
                node = row.get(holder)
                if isinstance(node, dict) and node.get("text"):
                    quoted = str(node["text"])[:110]
                    break
            lines.append(f"  · {head or row.get('record_id', '')} [{row.get('source_kind', '')}]"
                         + (f" {quoted}…" if quoted else ""))
    budget = payload.get("response_budget")
    if isinstance(budget, dict) and budget.get("truncated"):
        lines.append(f"축약: {budget.get('reduced_count', 0)}곳 — 생략분은 각 retrieval 경로로 확인")
    for key in ("next_item_offset", "next_offset"):
        if payload.get(key) not in (None, False):
            lines.append(f"이어보기: {key}={payload[key]} (같은 snapshot_id 사용)")
            break
    limits = payload.get("limitations") or payload.get("limits")
    if isinstance(limits, list) and limits:
        lines.append("한계: " + " / ".join(str(x) for x in limits[:2]))
    lines.append("전체 구조화 결과는 structuredContent에 있습니다.")
    text = "\n".join(lines)
    return text if len(text) <= _DIGEST_MAX else text[:_DIGEST_MAX] + "…"
