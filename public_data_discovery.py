"""Public Data Portal catalog discovery adapter.

This adapter searches *metadata only*. It is intentionally not a universal
runtime that blindly calls arbitrary APIs returned by the catalog.

Use case:
- discover official datasets/APIs that may strengthen a council briefing
  when council/law/finance evidence does not cover local statistics or
  domain-specific operational facts.

The actual data values must be retrieved through a separately reviewed adapter
for the selected API. This separation prevents arbitrary endpoint execution.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
from collections import OrderedDict
from typing import Any

import httpx

CATALOG_PAGE = "https://www.data.go.kr/data/15112888/openapi.do"
PRIMARY_KEY_ENV = "DATA_GO_KR_SEARCH_KEY"
URL_ENV = "DATA_GO_KR_SEARCH_URL"
DEFAULT_URL = "https://apis.data.go.kr/AAAAAAA/GetSearchDataList/v2/search"

_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_CACHE_TTL = 900
_CACHE_MAX = 64
_SEM = asyncio.Semaphore(1)


class DiscoveryError(RuntimeError):
    pass


def _key() -> str:
    return os.environ.get(PRIMARY_KEY_ENV, "").strip()


def _url() -> str:
    return os.environ.get(URL_ENV, "").strip() or DEFAULT_URL


def configuration() -> dict[str, Any]:
    return {
        "configured": bool(_key()),
        "env": {"key": PRIMARY_KEY_ENV, "url": URL_ENV},
        "endpoint": _url(),
        "catalog_page": CATALOG_PAGE,
        "role": "METADATA_DISCOVERY_ONLY",
        "note": (
            "공공데이터포털 검색서비스는 데이터값을 직접 제공하는 것이 아니라 "
            "키워드에 맞는 데이터셋/API 후보와 메타데이터를 찾는 용도입니다."
        ),
    }


def _cache_key(query: str, rows: int) -> str:
    import hashlib
    return hashlib.sha256(f"{query}|{rows}".encode()).hexdigest()


def _error_text(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False)
    except Exception:
        raw = str(value)
    return raw.upper()


def _looks_parameter_error(value: Any) -> bool:
    text = _error_text(value)
    return "INVALID_REQUEST_PARAMETER" in text or '"10"' in text or ">10<" in text


def _looks_auth_error(value: Any) -> bool:
    text = _error_text(value)
    return any(token in text for token in (
        "SERVICE_KEY_IS_NULL", "SERVICE_KEY_IS_NOT_REGISTERED",
        "SERVICE_ACCESS_DENIED", "PERMISSION_DENIED", "DEADLINE_HAS_EXPIRED",
        '"20"', '"30"', '"31"',
    ))


def _nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


def _pick(node: dict[str, Any], *keys: str) -> str:
    normalized = {re.sub(r"[_\s-]", "", str(k)).casefold(): v for k, v in node.items()}
    for key in keys:
        nk = re.sub(r"[_\s-]", "", key).casefold()
        value = normalized.get(nk)
        if value not in (None, "", [], {}):
            if isinstance(value, (dict, list)):
                continue
            return str(value).strip()
    return ""


def _candidate(node: dict[str, Any]) -> dict[str, Any] | None:
    title = _pick(node, "title", "dataName", "dataNm", "openApiNm", "apiNm", "datasetNm", "name")
    if not title or len(title) > 500:
        return None
    detail_url = _pick(node, "detailPageUrl", "detailUrl", "dataUrl", "url", "link", "dataDetailUrl")
    description = _pick(node, "description", "dataDc", "openApiDc", "desc", "summary")
    provider = _pick(node, "orgNm", "insttNm", "provider", "organization", "orgName")
    data_type = _pick(node, "dataType", "apiType", "type", "serviceType")
    identifier = _pick(node, "dataId", "openApiId", "id", "datasetId")
    return {
        "title": title[:500],
        "description": description[:1200],
        "provider": provider[:200],
        "data_type": data_type[:120],
        "identifier": identifier[:160],
        "detail_url": detail_url[:1000],
        "role": "DISCOVERY_CANDIDATE",
    }


def _extract_candidates(payload: Any, limit: int) -> list[dict[str, Any]]:
    out, seen = [], set()
    for node in _nodes(payload):
        if not isinstance(node, dict):
            continue
        item = _candidate(node)
        if not item:
            continue
        key = (item["title"], item["identifier"], item["detail_url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


async def _get(query: str, rows: int, keyword_param: str) -> Any:
    params = {
        "serviceKey": _key(),
        "pageNo": "1",
        "numOfRows": str(rows),
        keyword_param: query,
    }
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=False,
            headers={"User-Agent": "Uijeong-MCP/2.8 public-data-discovery"},
        ) as client:
            response = await client.get(_url(), params=params)
    except httpx.TransportError as exc:
        raise DiscoveryError("DATA_GO_KR_NETWORK_ERROR") from exc
    if response.status_code != 200:
        raise DiscoveryError(f"DATA_GO_KR_HTTP_{response.status_code}")
    if len(response.content) > 4_000_000:
        raise DiscoveryError("DATA_GO_KR_RESPONSE_TOO_LARGE")
    try:
        return response.json()
    except ValueError as exc:
        # Gateway errors sometimes arrive as XML/text. Never expose the key or body.
        raise DiscoveryError("DATA_GO_KR_NON_JSON_RESPONSE") from exc


async def search(query: str, limit: int = 8) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return {"status": "INVALID_INPUT", "message": "검색어는 1~200자 문자열이어야 합니다.", "items": []}
    if type(limit) is not int or not 1 <= limit <= 12:
        return {"status": "INVALID_INPUT", "message": "limit은 1~12입니다.", "items": []}
    cfg = configuration()
    if not cfg["configured"]:
        return {
            "status": "NOT_CONFIGURED",
            "message": "공공데이터포털 검색 API 키가 아직 설정되지 않았습니다.",
            "configuration": cfg,
            "items": [],
        }

    ck = _cache_key(query.strip(), limit)
    cached = _CACHE.get(ck)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        _CACHE.move_to_end(ck)
        return copy.deepcopy(cached[1])

    # Portal revisions have used slightly different keyword names. Try the
    # conservative common forms only when the first response explicitly says
    # the request parameter is invalid. Authentication errors never trigger retries.
    payload = None
    used_param = None
    async with _SEM:
        for keyword_param in ("keyword", "searchKeyword", "q"):
            try:
                candidate = await _get(query.strip(), max(10, limit), keyword_param)
            except DiscoveryError as exc:
                return {
                    "status": "ERROR",
                    "message": str(exc),
                    "configuration": cfg,
                    "items": [],
                    "limitations": ["검색 API 오류는 관련 공공데이터가 없다는 뜻이 아닙니다."],
                }
            if _looks_auth_error(candidate):
                return {
                    "status": "ERROR",
                    "message": "DATA_GO_KR_AUTH_ERROR",
                    "configuration": cfg,
                    "items": [],
                }
            if _looks_parameter_error(candidate):
                continue
            payload = candidate
            used_param = keyword_param
            break

    if payload is None:
        return {
            "status": "ERROR",
            "message": "DATA_GO_KR_PARAMETER_SCHEMA_UNCONFIRMED",
            "configuration": cfg,
            "items": [],
            "limitations": ["승인 화면의 실제 Swagger 요청변수와 endpoint를 확인해 매핑을 갱신해야 합니다."],
        }

    items = _extract_candidates(payload, limit)
    result = {
        "status": "COMPLETE" if items else "EMPTY",
        "query": query.strip(),
        "items": items,
        "coverage": {"keyword_parameter": used_param, "result_count": len(items)},
        "interpretation": (
            "이 결과는 공공데이터포털의 데이터셋/API 후보 메타데이터입니다. "
            "실제 수치나 사실을 의미하지 않으며, 후보 API는 별도 검토·연동 후 사용해야 합니다."
        ),
        "limitations": [
            "검색 0건은 해당 분야의 공공데이터가 전혀 없다는 뜻이 아닙니다.",
            "검색 결과의 API를 자동 실행하지 않습니다. 임의 외부 endpoint 실행을 막기 위한 설계입니다.",
        ],
    }
    _CACHE[ck] = (time.monotonic(), copy.deepcopy(result))
    _CACHE.move_to_end(ck)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result
