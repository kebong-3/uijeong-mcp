"""Evidence-first National Law Information API adapter for 지방의회MCP.

This module intentionally exposes only public law/ordinance search context.
It never treats an empty or failed upstream response as proof that no legal
basis exists. The Open API credential (LAW_OC) stays server-side.
"""
from __future__ import annotations

import asyncio
import copy
import html
import json
import os
import re
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode

import httpx

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
APPLICATION_URL = "https://open.law.go.kr/LSO/usrJoin.do"
GUIDE_URL = "https://open.law.go.kr/LSO/openApi/guideResult.do"

_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_CACHE_TTL = 600
_CACHE_MAX = 128
_SEM = asyncio.Semaphore(2)


class LawContextError(RuntimeError):
    pass


def _credential() -> str:
    return os.environ.get("LAW_OC", "").strip()


def configuration() -> dict[str, Any]:
    return {
        "configured": bool(_credential()),
        "env": "LAW_OC",
        "application_url": APPLICATION_URL,
        "guide_url": GUIDE_URL,
        "note": "국가법령정보 공동활용에서 본인이 신청한 API인증값(OC)을 입력합니다. Render에는 값만 저장하고 응답에 노출하지 않습니다.",
    }


def _norm_key(key: Any) -> str:
    return re.sub(r"[\s_]", "", str(key or ""))


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(x for x in (_clean(v) for v in value) if x)
    if isinstance(value, dict):
        return _clean(value.get("#text", value.get("_", "")))
    text = str(value)
    text = re.sub(r"<\s*(?:br\b[^>]*|/p|/div|/li)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]*>", "", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def _pick(obj: dict[str, Any], *keys: str) -> str:
    mapped = {_norm_key(k): v for k, v in obj.items()}
    for key in keys:
        if _norm_key(key) in mapped:
            value = _clean(mapped[_norm_key(key)])
            if value:
                return value
    return ""


def _nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nodes(child)


def _total_count(data: Any) -> int | None:
    for node in _nodes(data):
        value = _pick(node, "totalCnt", "totalCount")
        if value.isdigit():
            return int(value)
    return None


def _public_url(kind: str, doc_id: str, mst: str = "") -> str:
    if kind == "ordinance":
        params = {"ordinSeq": mst} if mst else {"ordinId": doc_id}
        return "https://www.law.go.kr/ordinInfoP.do?" + urlencode({k:v for k,v in params.items() if v})
    params = {"lsiSeq": mst} if mst else {"lsId": doc_id}
    return "https://www.law.go.kr/lsInfoP.do?" + urlencode({k:v for k,v in params.items() if v})


def _listing_rows(data: Any, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in _nodes(data):
        title = _pick(node, "자치법규명") if kind == "ordinance" else _pick(node, "법령명한글", "법령명_한글")
        doc_id = _pick(node, "자치법규ID") if kind == "ordinance" else _pick(node, "법령ID")
        mst = _pick(node, "자치법규일련번호") if kind == "ordinance" else _pick(node, "법령일련번호")
        if title and (doc_id or mst):
            rows.append({
                "kind": kind,
                "document_id": doc_id,
                "mst": mst,
                "title": title,
                "jurisdiction": _pick(node, "지자체기관명"),
                "effective_date": _pick(node, "시행일자"),
                "promulgation_date": _pick(node, "공포일자"),
                "amendment_type": _pick(node, "제개정구분명"),
                "document_type": _pick(node, "자치법규종류", "법령구분명"),
                "source_url": _public_url(kind, doc_id, mst),
            })
    out, seen = [], set()
    for row in rows:
        key = (row["document_id"], row["mst"], row["title"], row["jurisdiction"])
        if key not in seen:
            seen.add(key); out.append(row)
    return out


def _error_reported(data: Any) -> bool:
    for node in _nodes(data):
        if not isinstance(node, dict):
            continue
        lowered = {_norm_key(k).lower(): v for k,v in node.items()}
        for key in ("error", "errormsg", "errormessage", "errorcode"):
            if lowered.get(key):
                return True
        code = lowered.get("resultcode")
        if code and str(code).upper() not in {"0","00","200","SUCCESS","INFO-000"}:
            return True
    return False


def _cache_key(endpoint: str, params: dict[str, Any]) -> str:
    clean = json.dumps([endpoint, sorted((k,str(v)) for k,v in params.items())], ensure_ascii=False, separators=(",",":"))
    import hashlib
    return hashlib.sha256(clean.encode()).hexdigest()


async def _request(endpoint: str, params: dict[str, Any]) -> Any:
    oc = _credential()
    if not oc:
        raise LawContextError("LAW_OC_NOT_CONFIGURED")
    url = SEARCH_URL if endpoint == "search" else SERVICE_URL
    clean = {k:v for k,v in params.items() if v not in ("",None)}
    key = _cache_key(endpoint, clean)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        _CACHE.move_to_end(key)
        return copy.deepcopy(cached[1])
    async with _SEM:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False,
                                         headers={"User-Agent":"Uijeong-MCP/2.7 public-law-context"}) as client:
                resp = await client.get(url, params={**clean, "OC":oc, "type":"JSON"})
        except httpx.TransportError as exc:
            raise LawContextError("LAW_API_NETWORK_ERROR") from exc
    if resp.status_code != 200:
        raise LawContextError(f"LAW_API_HTTP_{resp.status_code}")
    if len(resp.content) > 6_000_000:
        raise LawContextError("LAW_API_RESPONSE_TOO_LARGE")
    try:
        data = resp.json()
    except ValueError as exc:
        raise LawContextError("LAW_API_NON_JSON_RESPONSE") from exc
    if not isinstance(data, (dict,list)) or _error_reported(data):
        raise LawContextError("LAW_API_REPORTED_ERROR")
    _CACHE[key] = (time.monotonic(), copy.deepcopy(data))
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return data


def _jurisdiction_aliases(value: str) -> set[str]:
    raw = re.sub(r"\s+", "", value or "")
    if not raw:
        return set()
    aliases = {raw.replace("의회","")}
    if "전남광주통합특별시서구" in raw:
        aliases |= {"전남광주통합특별시서구","광주광역시서구","광주서구"}
    return aliases


def _filter_jurisdiction(rows: list[dict[str, Any]], wanted: str) -> tuple[list[dict[str, Any]], bool]:
    aliases = _jurisdiction_aliases(wanted)
    if not aliases:
        return rows, True
    matched = []
    for row in rows:
        org = re.sub(r"\s+", "", row.get("jurisdiction") or "")
        if org and any(alias == org or alias in org or org in alias for alias in aliases):
            matched.append(row)
    return matched, bool(matched)


def _query_tokens(query: str) -> list[str]:
    stop = {"관련","사업","지원","운영","관리","조례","법령","법률","근거","의회","지방"}
    out=[]
    for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", query or ""):
        if token not in stop and token not in out:
            out.append(token)
    return out[:6]


def _article_rows(data: Any, query: str, limit: int = 5) -> list[dict[str,str]]:
    tokens = _query_tokens(query)
    candidates=[]
    for node in _nodes(data):
        if not isinstance(node, dict):
            continue
        body = _pick(node, "조내용", "조문내용")
        if not body:
            continue
        label = _pick(node, "조문번호")
        title = _pick(node, "조제목", "조문제목")
        canonical_label = label
        digits = re.fullmatch(r"\s*(\d+)\s*", label or "")
        if digits:
            canonical_label = f"제{digits.group(1)}조"
        hay = re.sub(r"\s+","", canonical_label+" "+label+" "+title+" "+body)
        score = 0
        for token in tokens:
            nt = re.sub(r"\s+","",token)
            if nt and nt in hay:
                score += 5 if nt == re.sub(r"\s+","",canonical_label) else 1
        if score:
            candidates.append((score, {"article":canonical_label or label, "title":title, "text":body[:1800]}))
    candidates.sort(key=lambda x:(-x[0], x[1]["article"]))
    return [item for _,item in candidates[:limit]]


async def search(query: str, kind: str, jurisdiction: str = "", limit: int = 6,
                 body_fallback: bool = True) -> dict[str, Any]:
    if kind not in {"law","ordinance"}:
        raise ValueError("kind must be law or ordinance")
    if not isinstance(query,str) or not query.strip() or len(query) > 200:
        raise ValueError("검색어는 1~200자입니다.")
    limit=max(1,min(int(limit),10))
    target = "ordin" if kind == "ordinance" else "law"
    params = {"target":target,"query":query.strip(),"display":min(100,max(20,limit*4)),"page":1,"search":1}
    if kind == "ordinance":
        params["nw"]=1
    data = await _request("search", params)
    rows = _listing_rows(data, kind)
    total = _total_count(data)
    if kind == "law":
        qn = re.sub(r"[^0-9A-Za-z가-힣]", "", query).casefold()
        def law_rank(row):
            tn = re.sub(r"[^0-9A-Za-z가-힣]", "", row.get("title","")).casefold()
            return (0 if tn == qn else 1 if tn.startswith(qn) else 2 if qn and qn in tn else 3, len(tn))
        rows.sort(key=law_rank)
    matched, jurisdiction_match = _filter_jurisdiction(rows, jurisdiction)
    selected = matched if jurisdiction and matched else rows
    used_body=False
    if body_fallback and len(selected) < min(2,limit):
        params["search"]=2
        body_data = await _request("search", params)
        body_rows = _listing_rows(body_data, kind)
        body_matched, body_jurisdiction_match = _filter_jurisdiction(body_rows, jurisdiction)
        add = body_matched if jurisdiction and body_matched else body_rows
        used_body=True
        jurisdiction_match = jurisdiction_match or body_jurisdiction_match
        seen={(r["document_id"],r["mst"]) for r in selected}
        for r in add:
            if (r["document_id"],r["mst"]) not in seen:
                selected.append(r); seen.add((r["document_id"],r["mst"]))
    return {
        "status":"COMPLETE" if selected else "EMPTY",
        "kind":kind,
        "query":query,
        "jurisdiction":jurisdiction or None,
        "jurisdiction_match":jurisdiction_match if jurisdiction else None,
        "api_total_title_search":total,
        "used_body_fallback":used_body,
        "items":selected[:limit],
        "limitations":[
            "검색 0건은 법적 근거가 없다는 뜻이 아닙니다. 정식 제명·본문·기관명·동의어로 재확인해야 합니다.",
            "자치법규 기관명 필터가 일치하지 않으면 전국 후보를 반환하고 jurisdiction_match=false로 표시합니다.",
        ],
    }


async def detail(item: dict[str, Any], query: str, max_articles: int = 5) -> dict[str, Any]:
    kind=item.get("kind")
    if kind not in {"law","ordinance"}:
        raise ValueError("잘못된 법령 후보입니다.")
    params={"target":"ordin" if kind=="ordinance" else "law"}
    if item.get("mst"):
        params["MST"]=item["mst"]
    elif item.get("document_id"):
        params["ID"]=item["document_id"]
    else:
        raise ValueError("법령 식별자가 없습니다.")
    data = await _request("service", params)
    return {
        **item,
        "matched_articles":_article_rows(data, query, max_articles),
        "detail_checked":True,
        "detail_note":"검색어와 직접 일치한 조문만 후보로 제시합니다. 최종 법적 판단은 전체 본문·부칙·시행일·별표를 공식 원문에서 확인하세요.",
    }


async def context(query: str, jurisdiction: str = "", include_articles: bool = True,
                  law_limit: int = 4, ordinance_limit: int = 6) -> dict[str, Any]:
    if not _credential():
        return {
            "status":"NOT_CONFIGURED",
            "message":"국가법령정보 공동활용 API 인증값이 아직 설정되지 않았습니다.",
            "configuration":configuration(),
            "laws":[],
            "ordinances":[],
        }
    try:
        laws, ordinances = await asyncio.gather(
            search(query,"law","",law_limit,True),
            search(query,"ordinance",jurisdiction,ordinance_limit,True),
        )
        if include_articles:
            async def enrich_many(rows, cap):
                tasks=[detail(x,query,4) for x in rows[:cap]]
                if not tasks:
                    return rows
                checked=await asyncio.gather(*tasks, return_exceptions=True)
                out=[]
                for idx,row in enumerate(rows):
                    if idx < cap and not isinstance(checked[idx],Exception):
                        out.append(checked[idx])
                    else:
                        out.append(row)
                return out
            laws["items"], ordinances["items"] = await asyncio.gather(
                enrich_many(laws["items"],2),
                enrich_many(ordinances["items"],3),
            )
        status="COMPLETE"
        if laws["status"]=="EMPTY" and ordinances["status"]=="EMPTY":
            status="EMPTY"
        return {
            "status":status,
            "query":query,
            "jurisdiction":jurisdiction or None,
            "laws":laws["items"],
            "ordinances":ordinances["items"],
            "coverage":{
                "law_search":laws["status"],
                "ordinance_search":ordinances["status"],
                "ordinance_jurisdiction_match":ordinances.get("jurisdiction_match"),
            },
            "limitations":laws["limitations"]+ordinances["limitations"]+[
                "이 결과는 의회 대응용 법령·조례 근거 후보입니다. 위임관계·시점법령·법률해석의 최종 판단은 조례뿌시기 등 전문 입법검토에서 추가 확인하세요."
            ],
        }
    except (LawContextError, ValueError) as exc:
        return {
            "status":"ERROR",
            "message":str(exc),
            "configuration":configuration(),
            "laws":[],
            "ordinances":[],
            "limitations":["API 오류를 법적 근거 없음으로 해석하지 마세요."],
        }
