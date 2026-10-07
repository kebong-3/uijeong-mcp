"""OpenAI standard search/fetch compatibility for the public council MCP.

The adapter adds the narrow read-only interface expected by ChatGPT company
knowledge and deep-research style MCP consumers without replacing the richer
employee workflow tools. Search results represent matching public meeting
passages, not private/user-provided documents.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time
import unicodedata
from collections import OrderedDict
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict

import runtime_security as R
import sources as S


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: str


class SearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[SearchResult]


class FetchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, Any] | None = None


_SEARCH_CACHE: "OrderedDict[str, tuple[float, SearchOutput]]" = OrderedDict()
_CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 128
_SEARCH_TIMEOUT_SECONDS = 55
_FETCH_TIMEOUT_SECONDS = 55
_RESULT_LIMIT = 10
CLIK_PORTAL_URL = "https://clik.nanet.go.kr/"

_FILLER = {
    "관련", "최근", "회의록", "회의", "질의", "답변", "질의답변", "발언", "의원", "집행부",
    "찾아줘", "찾아", "검색", "검색해줘", "정리", "정리해줘", "알려줘", "내용", "자료", "사례",
    "모두", "상세", "범위", "건", "관련해서", "관련한", "대한", "대해", "어떤", "있어", "있나",
    "비교", "분석", "최근자료", "원문", "근거", "의회",
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", value).removesuffix("의회")


@lru_cache(maxsize=1)
def _source_rows() -> tuple[dict[str, Any], ...]:
    return tuple(S.load_sources().get("sources", []))


def _best_council(query: str) -> tuple[str, set[str]]:
    """Return canonical council name and tokens to remove from the keyword.

    Longest known official/alias match wins. Ambiguous short names such as
    '서구' are intentionally not enough to override the configured default.
    """
    normalized = _norm(query)
    ranked: list[tuple[int, str, dict[str, Any], str]] = []
    for row in _source_rows():
        names = [row.get("name", ""), row.get("directory_name", ""), *(row.get("aliases") or [])]
        # Registry full names plus unique local-unit aliases support ordinary queries.
        for name in list(names):
            parts = str(name).split()
            if len(parts) > 1:
                names.append(parts[-1])
                province = parts[0]
                shortened = re.sub(r"(특별자치시|특별자치도|특별시|광역시|도)$", "", province)
                if shortened != province:
                    names.append(" ".join([shortened, *parts[1:]]))
        for name in names:
            n = _norm(name)
            if (len(n) < 2 or n not in normalized
                    or (len(n) == 2 and str(name) not in query)):
                continue
            # Prefer longer aliases, then aliases that include a province/city marker.
            specificity = int(any(mark in n for mark in (
                "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
                "경기", "강원", "충청", "충북", "충남", "전북", "전남", "경상", "경북", "경남", "제주"
            )))
            ranked.append((len(n), str(specificity), row, name))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)

    chosen = None
    if ranked:
        top_len = ranked[0][0]
        top = [x for x in ranked if x[0] == top_len]
        ids = {x[2].get("council_id") for x in top}
        if len(ids) == 1:
            chosen = top[0]

    default = os.environ.get("UIJEONG_DEFAULT_COUNCIL", "광주 서구").strip() or "광주 서구"
    if chosen is None:
        if ranked:
            raise ValueError("의회명이 모호합니다. 시·도와 시·군·구를 함께 지정하세요.")
        from jurisdiction_identity import resolve_jurisdiction
        local = []
        for token in re.findall(r"[가-힣]+", query):
            resolved = resolve_jurisdiction(token)
            if resolved['state'] == 'ambiguous':
                raise ValueError("지역명이 모호합니다. 시·도와 시·군·구를 함께 지정하세요.")
            if resolved['state'] == 'resolved':
                local.append((token,resolved))
        ids = {r['council_id'] for _,r in local}
        if len(ids)>1:
            raise ValueError("여러 지역명이 있어 모호합니다. 대상 의회를 하나로 지정하세요.")
        if local:
            token,resolved = local[0]
            return resolved['normalized']+'의회', {t for t,_ in local}
        return default, set()

    row, matched_name = chosen[2], chosen[3]
    from jurisdiction_identity import resolve_jurisdiction
    if resolve_jurisdiction(matched_name)['state'] == 'ambiguous':
        raise ValueError("의회명이 모호합니다. 시·도와 시·군·구를 함께 지정하세요.")
    drop_tokens: set[str] = set()
    for name in [matched_name, row.get("name", ""), *(row.get("aliases") or [])]:
        for token in re.findall(r"[0-9A-Za-z가-힣]+", str(name)):
            drop_tokens.add(token)
            drop_tokens.add(token.removesuffix("의회"))
            token = re.sub(r"(시|도|군|구)?의회$", "", token)
            if len(token) >= 2:
                drop_tokens.add(token)
            # Also remove common administrative suffixes from a token.
            stripped = re.sub(r"(특별자치시|특별자치도|특별시|광역시|자치구|시|군|구)$", "", token)
            if len(stripped) >= 2:
                drop_tokens.add(stripped)
    return row.get("name") or default, drop_tokens


def _keyword(query: str, drop_tokens: set[str]) -> str:
    value = unicodedata.normalize("NFKC", query)
    value = re.sub(r"최근\s*\d+\s*(년|개월|회계연도|회의연도)", " ", value)
    value = re.sub(r"20\d{2}\s*년(?:도)?", " ", value)
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", value)
    kept: list[str] = []
    for token in tokens:
        base = token.strip()
        particle_stripped = re.sub(r"(에서|으로|에게|부터|까지|하고|이며|이고|의|을|를|은|는|이|가)$", "", base)
        if base in _FILLER or particle_stripped in _FILLER:
            continue
        if base in drop_tokens or particle_stripped in drop_tokens:
            continue
        if re.fullmatch(r"\d+(년|개월|건)?", base):
            continue
        kept.append(particle_stripped or base)
    keyword = " ".join(x for x in kept if x).strip()
    if keyword:
        return keyword[:200]
    # Do not pass an empty query upstream. The original query is bounded later.
    return query.strip()[:200]


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return S.validate_official_source_url(value)
    except ValueError:
        return None


def _format_date(value: Any) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    return f"{text[:4]}.{text[4:6]}.{text[6:8]}." if len(text) >= 8 else ""


def _title(meta: dict[str, Any], kind: str = "") -> str:
    parts = [
        str(meta.get("council_name") or "").strip(),
        _format_date(meta.get("meeting_date")),
        str(meta.get("meeting_name") or "").strip(),
        kind.strip(),
    ]
    title = " · ".join(x for x in parts if x)
    return re.sub(r"\s+", " ", title).strip()[:300] or "지방의회 회의록"


def _ref_from_event(event: dict[str, Any]) -> str | None:
    docid = str(event.get("docid") or "").strip()
    if not docid:
        return None
    source = str((event.get("provenance") or {}).get("source") or "")
    return ("site:" + docid) if source == "SEOGU_SITE" and not docid.startswith("site:") else docid


def _anchor(event: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("question", "speech"):
        item = event.get(key)
        if isinstance(item, dict):
            return item
    answers = event.get("answers")
    if isinstance(answers, list) and answers and isinstance(answers[0], dict):
        return answers[0]
    return None


def _event_url(event: dict[str, Any], anchor: dict[str, Any] | None) -> str | None:
    citation = (anchor or {}).get("citation") if isinstance(anchor, dict) else None
    candidates = [
        (citation or {}).get("citation_url") if isinstance(citation, dict) else None,
        (event.get("provenance") or {}).get("citation_url"),
        (event.get("provenance") or {}).get("source_url"),
    ]
    for candidate in candidates:
        safe = _safe_url(candidate)
        if safe:
            return safe
    return None


def _encode_id(ref: str, turn: int, url: str) -> str:
    raw = json.dumps({"v": 1, "r": ref, "t": int(turn), "u": url},
                     ensure_ascii=False, separators=(",", ":")).encode()
    return "uc1_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_id(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value.startswith("uc1_") or len(value) > 4096:
        raise ValueError("지원되지 않는 검색 결과 ID입니다.")
    body = value[4:]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        obj = json.loads(raw)
    except Exception as exc:
        raise ValueError("검색 결과 ID를 해석할 수 없습니다.") from exc
    if (not isinstance(obj, dict) or obj.get("v") != 1
            or not isinstance(obj.get("r"), str)
            or not isinstance(obj.get("t"), int) or obj["t"] < 0
            or not _safe_url(obj.get("u"))):
        raise ValueError("검색 결과 ID가 올바르지 않습니다.")
    return obj


def _cache_get(query: str) -> SearchOutput | None:
    key = hashlib.sha256(query.strip().casefold().encode()).hexdigest()
    item = _SEARCH_CACHE.get(key)
    if not item:
        return None
    stamp, output = item
    if time.monotonic() - stamp > _CACHE_TTL_SECONDS:
        _SEARCH_CACHE.pop(key, None)
        return None
    _SEARCH_CACHE.move_to_end(key)
    return output


def _cache_put(query: str, output: SearchOutput) -> None:
    key = hashlib.sha256(query.strip().casefold().encode()).hexdigest()
    _SEARCH_CACHE[key] = (time.monotonic(), output)
    _SEARCH_CACHE.move_to_end(key)
    while len(_SEARCH_CACHE) > _CACHE_MAX_ENTRIES:
        _SEARCH_CACHE.popitem(last=False)


def build_tools(backend: Any) -> dict[str, Any]:
    async def search(query: str) -> SearchOutput:
        """Search public local-council minutes for a natural-language query.

        Include a council name when searching outside the default Gwangju Seo-gu
        council. Results are matching public meeting passages with canonical,
        user-openable source URLs. If CLIK omits a document link, the URL is
        the official service portal, explicitly marked in the title; fetch
        preserves the official document ID and parsed-turn locator.
        """
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("query는 1~300자 문자열이어야 합니다.")
        cached = _cache_get(query)
        if cached is not None:
            return cached

        council, drop = _best_council(query)
        from query_decomposition import natural_council_query
        plan = natural_council_query(query, council)
        # Preserve established council removal (including alias spellings) and
        # reuse the shared topic parser on the remainder, not a weak second search.
        stripped = _keyword(query, drop)
        cleaned = natural_council_query(stripped, council)
        terms = plan["terms"] if plan["speaker_ranking_candidate"] else cleaned["terms"]
        keyword = terms[0]

        async def run() -> dict[str, Any]:
            return await backend.council_evidence_bundle(
                keyword=keyword, council=council, mode="발언",
                max_docs=4, source="auto", limit=20,
                search_terms=terms[1:] or None, **plan["period"],
            )

        try:
            payload = await asyncio.wait_for(run(), timeout=_SEARCH_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(R.safe_error(exc)) from None

        if not isinstance(payload, dict):
            raise RuntimeError("지방의회 검색 결과 형식이 올바르지 않습니다.")
        if payload.get("status") == "ERROR":
            raise RuntimeError("지방의회 공개자료 조회에 실패했습니다.")

        results: list[SearchResult] = []
        seen: set[tuple[str, int]] = set()
        events = list(payload.get("items") or [])
        speaker = plan["speaker_ranking_candidate"]
        if speaker:
            # Rank matching *retrieved* labels. Never fabricate the requested
            # speaker or discard all results when the name candidate is wrong.
            events.sort(key=lambda event: speaker not in str((_anchor(event) or {}).get("label", "")))
        for event in events:
            if not isinstance(event, dict):
                continue
            anchor = _anchor(event)
            ref = _ref_from_event(event)
            url = _event_url(event, anchor)
            turn = (anchor or {}).get("turn_index")
            if not ref or not isinstance(turn, int):
                continue
            direct_url = url is not None
            url = url or CLIK_PORTAL_URL
            key = (ref, turn)
            if key in seen:
                continue
            seen.add(key)
            results.append(SearchResult(
                id=_encode_id(ref, turn, url),
                title=_title(event.get("metadata") or {}, str(event.get("kind") or "")) +
                      (" · " + str(anchor.get("label")) if anchor.get("label") else "") +
                      (" [일부 검색범위]" if payload.get("status") == "PARTIAL" else "") +
                      ("" if direct_url else " [CLIK 원문링크 미제공]"),
                url=url,
            ))
            if len(results) >= _RESULT_LIMIT:
                break

        output = SearchOutput(results=results)
        if results or payload.get("status") in ("COMPLETE", "EMPTY"):
            _cache_put(query, output)
        return output

    async def fetch(id: str) -> FetchOutput:
        """Fetch one search-result passage with nearby official meeting context."""
        try:
            decoded = _decode_id(id)
        except ValueError:
            raise

        ref, turn, original_url = decoded["r"], decoded["t"], decoded["u"]
        start_turn = max(0, turn - 2)

        async def run() -> dict[str, Any]:
            return await backend.council_read_source(
                ref=ref, start_turn=start_turn, start_char=0,
                max_turns=14, max_chars=18000, whole_agenda=False,
            )

        try:
            page = await asyncio.wait_for(run(), timeout=_FETCH_TIMEOUT_SECONDS)
        except Exception as exc:
            raise RuntimeError(R.safe_error(exc)) from None

        if not isinstance(page, dict) or page.get("status") in ("ERROR", "INVALID_INPUT"):
            raise RuntimeError("회의록 원문을 가져오지 못했습니다.")

        meta = page.get("meta") or {}
        current_url = _safe_url((page.get("source_link") or {}).get("url"))
        url = current_url or _safe_url(page.get("source_url")) or original_url
        if not url:
            raise RuntimeError("사용자가 열 수 있는 공식 원문 주소를 확인하지 못했습니다.")

        lines: list[str] = []
        title = _title(meta)
        if title:
            lines.append(title)
        lines.append(f"참조: {ref}")
        for item in page.get("turns") or []:
            if not isinstance(item, dict):
                continue
            idx = item.get("idx")
            label = re.sub(r"[\r\n]+", " ", str(item.get("label") or "")).strip()
            context = re.sub(r"[\r\n]+", " ", str(item.get("speech_context") or "")).strip()
            text_value = str(item.get("text") or "").strip()
            prefix = f"#{idx}" if isinstance(idx, int) else "#?"
            if context:
                prefix += f" [{context}]"
            if label:
                prefix += f" {label}"
            lines.append(prefix + ": " + text_value)

        if page.get("next_start_turn") is not None:
            lines.append("[이 검색 항목은 관련 발언 주변 문맥을 반환하며 회의록 전체 전문은 아닙니다.]")

        metadata = {
            "source": "public_local_council_minutes",
            "ref": ref,
            "meeting_date": meta.get("meeting_date"),
            "meeting_name": meta.get("meeting_name"),
            "council_name": meta.get("council_name"),
            "citation_status": (page.get("source_link") or {}).get("status"),
            "url_kind": "OFFICIAL_SERVICE_PORTAL" if url == CLIK_PORTAL_URL else "DOCUMENT_REFERENCE",
            "direct_document_url": url != CLIK_PORTAL_URL,
            "citation_note": "CLIK 제공 원문 주소가 없습니다. URL은 공식 서비스 안내이며 문서 ID·발언번호로 대조하세요." if url == CLIK_PORTAL_URL else None,
            "scope": "matching_passage_with_context",
            "start_turn": start_turn,
            "matched_turn": turn,
            "partial_context": page.get("next_start_turn") is not None,
        }
        return FetchOutput(
            id=id,
            title=title or "지방의회 회의록",
            text="\n".join(lines).strip(),
            url=url,
            metadata=metadata,
        )

    # Preserve canonical tool names and exact return annotations for schema inference.
    search.__name__ = "search"
    fetch.__name__ = "fetch"
    return {"search": search, "fetch": fetch}


STANDARD_TOOL_NAMES = ("search", "fetch")
