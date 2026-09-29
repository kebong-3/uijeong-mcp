"""v3.0.1 stability layer; preserve the 21 public read-only tool contracts."""
from __future__ import annotations
import asyncio
import copy
import datetime as dt
import functools
import hashlib
import inspect
import json
import os
import re
import time
import uuid
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

KST = dt.timezone(dt.timedelta(hours=9))
VERSION = "3.0.2-public.1"
METRICS = {"requests": 0, "cache_hits": 0, "coalesced": 0, "executions": 0, "errors": 0}
_CACHE = OrderedDict()
_FLIGHTS = {}
_LOOP = None
_LAST_CHECK = {}
CACHE_ENTRIES = 48
CACHE_BYTES = 8 * 1024 * 1024
CACHE_TTL = 30
PROFILES = {
    "휴라운지": {"minutes": ["휴 라운지", "휴(休) 라운지"], "finance": ["직원 후생복지", "후생복지"], "legal": ["공무원 후생복지"], "peer": ["직원 휴게공간", "휴게실"]},
    "직원휴게공간": {"minutes": ["직원 휴게실", "직원 쉼터"], "finance": ["직원 후생복지", "청사 환경개선"], "legal": ["공무원 후생복지"], "peer": ["직원 휴게실", "휴게실"]},
    "체납관리단": {"minutes": ["체납 관리단"], "finance": ["체납관리", "체납징수"], "legal": ["지방세징수"], "peer": ["체납 관리단", "체납실태조사"]},
}


def today():
    return dt.datetime.now(KST).date()


def norm(value):
    import unicodedata
    return re.sub(r"[^0-9A-Za-z가-힣]", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def expansions(topic, purpose="minutes", limit=2):
    key = norm(topic)
    for name, profile in PROFILES.items():
        if norm(name) in key:
            return profile.get(purpose, [])[:limit]
    return []


def valid_period(start, end):
    parsed = []
    for value in (start, end):
        if value in (None, ""):
            parsed.append(None)
        elif not isinstance(value, str) or not re.fullmatch(r"\d{4}-?\d{2}-?\d{2}", value):
            raise ValueError("날짜는 YYYY-MM-DD 또는 YYYYMMDD 형식이어야 합니다.")
        else:
            parsed.append(dt.datetime.strptime(value.replace("-", ""), "%Y%m%d").date())
    if parsed[0] and parsed[1] and parsed[0] > parsed[1]:
        raise ValueError("시작일이 종료일보다 늦습니다.")
    return tuple(x.strftime("%Y-%m-%d") if x else None for x in parsed)


def aggregate_status(stages):
    statuses = [x.get("status", "ERROR") for x in stages.values() if isinstance(x, dict) and x.get("status") != "SKIPPED"]
    if not statuses:
        return "EMPTY"
    if any(x not in {"COMPLETE", "EMPTY"} for x in statuses):
        return "ERROR" if all(x in {"ERROR", "INVALID_INPUT"} for x in statuses) else "PARTIAL"
    return "EMPTY" if all(x == "EMPTY" for x in statuses) else "COMPLETE"


def safe_url(value, host=None):
    if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\x00-\x20]", value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        if host and p.hostname not in {host, "www." + host}:
            return None
        if any(k.lower() in {"oc", "servicekey", "apikey", "api_key", "access_token", "token"} for k, _ in parse_qsl(p.query)):
            return None
        return value
    except (ValueError, TypeError):
        return None


async def stage(awaitable, seconds=30):
    import runtime_security as R
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(awaitable, timeout=seconds)
        if not isinstance(result, dict):
            return {"status": "ERROR", "code": "INVALID_LAYER_RESPONSE"}
        result = dict(result)
    except asyncio.TimeoutError:
        result = {"status": "ERROR", "code": "LAYER_TIMEOUT", "message": "이 출처의 시간 제한에 도달했습니다. 다른 출처의 결과는 유지됩니다."}
    except Exception as exc:
        result = {"status": "ERROR", "code": "LAYER_FAILED", "message": R.safe_error(exc)}
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def _receipt(result, tool, started, mode):
    result = copy.deepcopy(result)
    if isinstance(result, dict):
        result["mcp_receipt"] = {
            "request_id": uuid.uuid4().hex[:20], "tool": tool, "server_version": VERSION,
            "returned_at": dt.datetime.now(KST).isoformat(), "elapsed_ms": round((time.monotonic() - started) * 1000),
            "result_reuse": mode,
            "meaning": "서버 도구 실행/결과 반환 기록입니다. 각 외부 API의 성공이나 근거 완전성은 별도 status·coverage를 확인하세요.",
        }
    return result


async def run_public(fn, args, kwargs):
    """Coalesce identical lookups; bounded by entries AND serialized bytes."""
    global _LOOP
    import runtime_security as R
    started = time.monotonic()
    METRICS["requests"] += 1
    name = fn.__name__
    loop = asyncio.get_running_loop()
    if _LOOP is not loop:
        _FLIGHTS.clear()
        _LOOP = loop
    binding = inspect.signature(fn).bind(*args, **kwargs)
    binding.apply_defaults()
    excluded = {"council_status", "council_read_source", "council_open_record", "council_get_evidence"}
    reusable = name not in excluded and not binding.arguments.get("snapshot_id")
    raw = json.dumps([name, R.REQUEST_SCOPE.get(), binding.arguments], ensure_ascii=False, sort_keys=True, default=str)
    key = hashlib.sha256(raw.encode()).hexdigest()
    for old in list(_CACHE):
        if time.monotonic() - _CACHE[old][0] > CACHE_TTL:
            _CACHE.pop(old, None)
    cached = _CACHE.get(key) if reusable else None
    if cached:
        _CACHE.move_to_end(key)
        METRICS["cache_hits"] += 1
        return _receipt(cached[2], name, started, "short_cache")

    async def execute():
        METRICS["executions"] += 1
        try:
            result = await asyncio.wait_for(fn(*args, **kwargs), timeout=56)
        except BaseException:
            METRICS["errors"] += 1
            raise
        if isinstance(result, dict) and result.get("status") == "ERROR":
            METRICS["errors"] += 1
        if reusable and isinstance(result, dict) and result.get("status") == "COMPLETE":
            size = len(json.dumps(result, ensure_ascii=False, default=str).encode())
            if size <= 256 * 1024:
                _CACHE[key] = (time.monotonic(), size, copy.deepcopy(result))
                while len(_CACHE) > CACHE_ENTRIES or sum(x[1] for x in _CACHE.values()) > CACHE_BYTES:
                    _CACHE.popitem(last=False)
        return result

    if not reusable:
        return _receipt(await execute(), name, started, "fresh")
    task = _FLIGHTS.get(key)
    mode = "coalesced" if task else "fresh"
    if task:
        METRICS["coalesced"] += 1
    else:
        task = asyncio.create_task(execute())
        _FLIGHTS[key] = task
        def done(t):
            if _FLIGHTS.get(key) is t:
                _FLIGHTS.pop(key, None)
            if not t.cancelled():
                t.exception()
        task.add_done_callback(done)
    return _receipt(await asyncio.shield(task), name, started, mode)


def canonical_jurisdiction(value):
    value = norm(str(value or "").replace("의회", ""))
    aliases = {"광주서구": "전남광주통합특별시서구", "광주광역시서구": "전남광주통합특별시서구",
               "서울용산구": "서울특별시용산구", "경북경산시": "경상북도경산시"}
    return aliases.get(value, value)


def law_jurisdiction(rows, wanted):
    target = canonical_jurisdiction(wanted)
    if not target:
        return rows, True
    matched = [r for r in rows if canonical_jurisdiction(r.get("jurisdiction", "")) == target]
    return matched, bool(matched)


def number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
        if not parsed.is_finite():
            return None
        return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)
    except (InvalidOperation, ValueError):
        return None


def finance_belongs(row, council):
    if not council:
        return True
    return canonical_jurisdiction(row.get("laf_hg_nm", "")) == canonical_jurisdiction(council)


def result_code(payload):
    """Inspect error fields, never arbitrary values such as a row containing 30."""
    if isinstance(payload, dict):
        for key in ("resultCode", "result_code", "returnReasonCode", "errCd"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        for key in ("header", "RESULT", "response", "cmmMsgHeader", "OpenAPI_ServiceResponse"):
            code = result_code(payload.get(key))
            if code is not None:
                return code
        if "CODE" in payload and "MESSAGE" in payload:
            return str(payload["CODE"])
    elif isinstance(payload, list):
        for value in payload[:3]:
            code = result_code(value)
            if code is not None:
                return code
    return None


def payload_shape(payload, depth=0):
    if depth > 3:
        return type(payload).__name__
    if isinstance(payload, dict):
        return {str(k)[:60]: payload_shape(v, depth + 1) for k, v in list(payload.items())[:16]}
    if isinstance(payload, list):
        return [payload_shape(payload[0], depth + 1)] if payload else []
    return type(payload).__name__


def parse_discovery(payload, limit=6):
    import public_data_discovery as D
    if not isinstance(payload, (dict, list)):
        return {"status": "ERROR", "code": "CATALOG_SCHEMA_UNCONFIRMED", "items": []}
    code = result_code(payload)
    if code is not None and code.upper() not in {"0", "00", "0000", "200", "SUCCESS", "INFO-000", "INFO-200"}:
        return {"status": "ERROR", "code": "CATALOG_UPSTREAM_ERROR", "upstream_code": code[:30], "items": []}
    items = []
    for item in D._extract_candidates(payload, limit):
        url = safe_url(item.get("detail_url"), "data.go.kr")
        item = dict(item, detail_url=url, role="DISCOVERY_CANDIDATE", actual_values_fetched=False)
        if url or item.get("identifier") or item.get("provider"):
            items.append(item)
    if items:
        return {"status": "COMPLETE", "items": items, "schema_recognized": True}
    empty = False
    for node in D._nodes(payload):
        if not isinstance(node, dict):
            continue
        for key in ("items", "list", "results", "documents", "data"):
            if key in node and node[key] == []:
                empty = True
        for key in ("totalCount", "totalCnt", "total_count"):
            if key in node and str(node[key]) == "0":
                empty = True
    if code == "INFO-200" or empty:
        return {"status": "EMPTY", "items": [], "schema_recognized": True}
    return {"status": "ERROR", "code": "CATALOG_SCHEMA_UNCONFIRMED", "items": [],
            "schema_shape": payload_shape(payload), "schema_recognized": False,
            "message": "응답이 왔지만 목록 구조를 확인하지 못했습니다. 자료 없음으로 판단하지 않습니다."}


async def discovery_search(query: str, limit: int = 8) -> dict[str, Any]:
    import public_data_discovery as D
    import runtime_security as R
    if not isinstance(query, str) or not query.strip() or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 12:
        return {"status": "INVALID_INPUT", "items": []}
    cfg = D.configuration()
    if not cfg["configured"]:
        return {"status": "NOT_CONFIGURED", "configuration": cfg, "items": []}
    p = urlsplit(D._url())
    if p.scheme != "https" or p.hostname != "apis.data.go.kr" or p.port not in (None,443) or p.path != "/AAAAAAA/GetSearchDataList/v2/search" or p.query or p.fragment or p.username:
        return {"status": "ERROR", "code": "CATALOG_ENDPOINT_NOT_ALLOWED", "items": []}
    parameter = os.environ.get("DATA_GO_KR_SEARCH_QUERY_PARAM", "keyword").strip()
    if parameter not in {"keyword", "searchKeyword", "q"}:
        return {"status": "ERROR", "code": "CATALOG_PARAMETER_NOT_ALLOWED", "items": []}
    try:
        async with D._SEM:
            payload = await D._get(query.strip(), max(10, limit), parameter)
        result = parse_discovery(payload, limit)
    except Exception as exc:
        result = {"status": "ERROR", "code": "CATALOG_FETCH_FAILED", "message": R.safe_error(exc), "items": []}
    result.update(query=query.strip(), configuration=cfg,
                  interpretation="공식 데이터셋 후보 메타데이터입니다. 실제 수치 조회·별도 API 자동 실행이 아닙니다.")
    _LAST_CHECK["public_data_search"] = {"status": result["status"], "checked_at": dt.datetime.now(KST).isoformat(), "items": len(result.get("items", [])), "code": result.get("code")}
    return result


async def legal_context(query: str, jurisdiction: str = "", include_articles: bool = True,
                        law_limit: int = 4, ordinance_limit: int = 6) -> dict[str, Any]:
    import legal_context as L
    if not L.configuration()["configured"]:
        return {"status": "NOT_CONFIGURED", "configuration": L.configuration(), "laws": [], "ordinances": []}
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        return {"status": "INVALID_INPUT", "laws": [], "ordinances": []}
    lookup_term = (expansions(query, "legal", 1) or [query.strip()])[0]

    async def lookup(kind, limit):
        limit = max(1, min(10, int(limit)))
        terms = [lookup_term]
        if kind == "ordinance" and jurisdiction:
            terms = [f"{jurisdiction} {lookup_term}"]
            if "전남광주통합특별시 서구" in jurisdiction:
                terms.append(f"{jurisdiction.replace('전남광주통합특별시', '광주광역시')} {lookup_term}")
        attempts, selected, total, rows = [], [], None, []
        for term in terms[:2]:
            params = {"target": "ordin" if kind == "ordinance" else "law", "query": term,
                      "display": 100 if kind == "ordinance" else 20, "page": 1, "search": 1}
            if kind == "ordinance":
                params["nw"] = 1
            data = await L._request("search", params)
            total = L._total_count(data)
            rows = L._listing_rows(data, kind)
            if total is None and not rows:
                return {"status": "ERROR", "code": "LAW_SCHEMA_UNCONFIRMED", "items": []}
            local, _ = law_jurisdiction(rows, jurisdiction) if kind == "ordinance" else (rows, True)
            attempts.append({"query": term, "api_total": total, "returned": len(rows), "local_candidates": len(local)})
            if local:
                selected = local[:limit]
                break
        for row in selected:
            row["match_status"] = "CANDIDATE"
            row["applicability_verified"] = False
            row["scope_note"] = "의회사무기구 직원 관련 조례 여부 확인" if "의회" in row.get("title", "") else "적용대상·상위법·시행일 별도 검토"
        detail_errors = []
        if include_articles and selected:
            checks = await asyncio.gather(*(stage(L.detail(row, lookup_term, 4), 12) for row in selected[:2]))
            for i, checked in enumerate(checks):
                if checked.get("detail_checked"):
                    selected[i].update(checked)
                    selected[i]["applicability_verified"] = False
                else:
                    detail_errors.append({"title":selected[i].get("title"), "status":checked.get("status","ERROR")})
        limited = bool(total and total > len(rows)) or len(rows) > limit or bool(detail_errors)
        return {"status": ("PARTIAL" if limited else "COMPLETE") if selected else "EMPTY",
                "items": selected, "attempts": attempts, "detail_errors":detail_errors,
                "jurisdiction_match": bool(selected) if kind == "ordinance" and jurisdiction else None}

    law, ordin = await asyncio.gather(stage(lookup("law", law_limit), 22), stage(lookup("ordinance", ordinance_limit), 22))
    status = aggregate_status({"law": law, "ordinance": ordin})
    result = {"status": status, "query": query, "lookup_term": lookup_term, "jurisdiction": jurisdiction,
              "laws": law.get("items", []), "ordinances": ordin.get("items", []),
              "coverage": {"law_search": law["status"], "ordinance_search": ordin["status"],
                           "ordinance_jurisdiction_match": ordin.get("jurisdiction_match"),
                           "law_attempts": law.get("attempts", []), "ordinance_attempts": ordin.get("attempts", [])},
              "errors": [x for x in (law, ordin) if x["status"] == "ERROR"],
              "checked_at": dt.datetime.now(KST).isoformat(), "version_scope": "CURRENT_LOOKUP_NOT_HISTORICAL_OPINION",
              "legal_conclusion_verified": False,
              "limitations": ["다른 지역 조례를 대상 지자체의 조례로 반환하지 않습니다.", "조례 후보 발견은 해당 사업의 적법성이나 지출근거 확정이 아닙니다.", "과거 회의 당시 적용법령·부칙·별표·위임관계는 별도로 확인해야 합니다."]}
    _LAST_CHECK["law"] = {"status": status, "local_candidates": len(result["ordinances"]), "checked_at": result["checked_at"]}
    return result


async def finance_context(topic: str, council: str = "", fiscal_year: Optional[int] = None,
                          limit: int = 20, search_terms: Optional[list[str]] = None) -> dict[str, Any]:
    import finance_context as F
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200 or type(limit) is not int or not 1 <= limit <= 50:
        return {"status": "INVALID_INPUT", "items": []}
    year = today().year if fiscal_year is None else fiscal_year
    if type(year) is not int or not 2016 <= year <= today().year:
        return {"status": "INVALID_INPUT", "message": "회계연도는 2016년부터 현재연도 사이입니다.", "items": []}
    cfg = F.configuration()
    if not cfg["configured"]:
        return {"status": "NOT_CONFIGURED", "configuration": cfg, "items": []}
    if search_terms is not None and (not isinstance(search_terms,list) or any(not isinstance(t,str) or len(t)>100 for t in search_terms)):
        return {"status":"INVALID_INPUT", "items":[]}
    terms = [topic.strip()]
    for term in search_terms or expansions(topic, "finance"):
        if term.strip() and term.strip() not in terms:
            terms.append(term.strip())
        if len(terms) == 3:
            break
    date = today().strftime("%Y%m%d") if year == today().year else f"{year}1231"
    attempts, found, errors, seen = [], [], [], set()
    incomplete = False
    for term in terms:
        checked = await stage(F._request({"fyr": str(year), "dbiz_nm": term, "exe_ymd": date, "pSize":1000}), 16)
        if checked.get("status") == "ERROR":
            errors.append(checked)
            break
        rows = checked.get("rows", [])
        total = int(checked.get("total_count") or 0)
        incomplete |= total > len(rows)
        local = [r for r in rows if finance_belongs(r, council) and str(r.get("fyr") or year) == str(year)]
        attempts.append({"term": term, "upstream_total": total, "rows_received": len(rows), "matched_local_government":len(local), "response_code":checked.get("result_code")})
        for row in local:
            key = (str(row.get("laf_cd") or row.get("laf_hg_nm")), str(row.get("dbiz_cd") or row.get("dbiz_nm")), str(row.get("exe_ymd")), str(row.get("acnt_dv_nm")))
            if key in seen:
                continue
            seen.add(key)
            item = F._public_row(row)
            item["match_status"] = "RELATED_PROJECT_CANDIDATE" if term != topic.strip() else "PROJECT_NAME_MATCH_CANDIDATE"
            item["matched_query"] = term
            item["same_project_verified"] = False
            found.append(item)
        if found:
            break
    if errors:
        status = "PARTIAL" if found or attempts else "ERROR"
    elif incomplete or len(found) > limit:
        status = "PARTIAL"
    else:
        status = "COMPLETE" if found else "EMPTY"
    result = {"status": status, "source": "행정안전부 지방재정365 세부사업별 세출현황", "service_code": F.SERVICE_CODE,
              "dataset_url": F.DATASET_URL, "query": {"topic": topic, "council": council, "fiscal_year": year, "snapshot_date": date},
              "items": found[:limit], "upstream_total": sum(x["upstream_total"] for x in attempts), "matched_local_government_count": len(found),
              "search_strategy": {"exact_first": True, "progressive_widening": len(attempts) > 1, "attempts": attempts},
              "coverage": {"limited": incomplete or len(found) > limit, "is_exhaustive": False, "scanned_pages_per_query":1, "has_unread_pages":incomplete},
              "errors": errors, "configured": True,
              "limitations": ["조회일 자료가 아직 제공되지 않거나 사업명이 다를 수 있습니다. 미발견을 예산 없음으로 단정하지 않습니다.", "서로 다른 지출일 자료를 합산하지 않습니다. 본예산·추경 의결액은 예산서와 별도로 대조하세요.", "관련 세부사업 후보는 동일 사업·동일 회계의 확정 근거가 아닙니다."]}
    _LAST_CHECK["finance365"] = {"status": status, "items": len(found), "checked_at":dt.datetime.now(KST).isoformat()}
    return result


async def finance_ping() -> dict[str, Any]:
    import finance_context as F
    if not F.configuration()["configured"]:
        return {"status": "NOT_CONFIGURED", "configured": False}
    checked = await stage(F._request({"fyr":str(today().year), "exe_ymd":today().strftime("%Y%m%d"), "pSize":1}),16)
    if checked.get("status") == "ERROR":
        return checked
    count = len(checked.get("rows", []))
    return {"status":"COMPLETE" if count else "PARTIAL", "configured":True,
            "response_code":checked.get("result_code"), "sample_rows_received":count, "data_returned":bool(count),
            "note":"접속 응답과 실제 사업자료 검증은 별개입니다."}


async def context_pack(U, topic: str, council: str = "광주 서구", date_from: Optional[str] = None,
                       date_to: Optional[str] = None, include_legal: bool = True, include_finance: bool = True,
                       include_public_data: bool = False, fiscal_year: Optional[int] = None, max_docs: int = 4) -> dict[str, Any]:
    import council_extensions as C
    import legal_context as L
    import finance_context as F
    import public_data_discovery as D
    if not isinstance(topic,str) or not topic.strip() or len(topic)>200 or type(max_docs) is not int or not 1<=max_docs<=6:
        return {"status":"INVALID_INPUT", "message":"공개 주제어와 상세 건수(1~6)를 확인하세요."}
    try:
        date_from, date_to = valid_period(date_from,date_to)
    except ValueError as exc:
        return {"status":"INVALID_INPUT", "message":str(exc)}
    cid,cname,error = U.pick_council(council)
    if error:
        return {"status":"INVALID_INPUT", "message":error}
    scope = {"keyword":topic.strip(), "council":council, "date_from":date_from,"date_to":date_to,
             "max_docs":max_docs,"source":"auto","limit":8}
    tasks = {"council_evidence":U.council_evidence_bundle(**scope,mode="질의답변"),
             "related_bills":C._bill_context(U,topic.strip(),cid,2),
             "member_record_discovery":C._member_discovery(U,topic.strip(),cid,2),
             "policy_background":C._policy_context(U,topic.strip(),1)}
    if include_legal:
        tasks["legal_and_ordinance_context"] = L.context(topic.strip(),C._jurisdiction_from_council(cname),include_articles=True)
    if include_finance:
        tasks["finance_context"] = F.context(topic.strip(),cname,fiscal_year,10)
    if include_public_data:
        tasks["public_data_discovery"] = D.search(topic.strip(),6)
    results = await asyncio.gather(*(stage(task,30) for task in tasks.values()))
    layers = dict(zip(tasks,results))
    for name in ("legal_and_ordinance_context","finance_context","public_data_discovery"):
        layers.setdefault(name,{"status":"SKIPPED"})
    evidence = layers["council_evidence"]
    report = {"status":"SKIPPED"}
    if not evidence.get("items") and evidence.get("status") != "ERROR":
        report = await stage(U.council_evidence_bundle(**{**scope,"max_docs":min(max_docs,2)},
                    mode="발언",search_terms=expansions(topic,"minutes")),16)
    layers["report_mentions"] = report
    return {"status":aggregate_status(layers), "topic":topic.strip(),"council":{"id":cid,"name":cname}, **layers,
            "search_strategy":{"exact_first":True,"expanded":False,"report_pass_separate":report.get("status")!="SKIPPED"},
            "coverage_card":{"date_from":date_from,"date_to":date_to,"search_terms":[topic.strip()],
                "evidence_coverage":evidence.get("coverage",[]),"coverage_summary":evidence.get("coverage_summary",{}),"is_exhaustive":False},
            "execution_trace":{"mcp_tool":"council_context_pack","stages":[{"stage":k,"status":v["status"],"elapsed_ms":v.get("elapsed_ms")} for k,v in layers.items()]},
            "interpretation":["report_mentions의 집행부 업무보고는 의원 질의가 아닙니다.","법령·예산·의원정보·정책정보는 용도별 후보이며 발언 사실은 회의록 원문으로 확인합니다.","각 출처의 오류·미설정·검색범위를 그대로 표시해야 합니다."],
            "ready_for_submission":False}


def install(U):
    """Replace implementations without removing or renaming public tools."""
    if getattr(U,"_v3_reliability_installed",False):
        return
    import legal_context as L
    import finance_context as F
    import public_data_discovery as D
    L._filter_jurisdiction = law_jurisdiction
    L.context = legal_context
    F._belongs = finance_belongs
    F._num = number
    old_row = F._public_row
    def public_row(row):
        result = old_row(row)
        budget,spent = result.get("budget_current_amount"),result.get("expenditure")
        result["execution_rate_percent"] = round(float(Decimal(str(spent))*100/Decimal(str(budget))),1) if budget is not None and budget>0 and spent is not None else None
        return result
    F._public_row = public_row
    F.context = finance_context
    F.ping = finance_ping
    D.search = discovery_search

    async def council_context_pack(topic: str, council: str = "광주 서구", date_from: Optional[str] = None,
            date_to: Optional[str] = None, include_legal: bool = True, include_finance: bool = True,
            include_public_data: bool = False, fiscal_year: Optional[int] = None, max_docs: int = 4) -> dict[str, Any]:
        """출처별 실패를 보존하는 근거팩. 업무보고와 의원 질의를 구분합니다."""
        return await context_pack(U,topic,council,date_from,date_to,include_legal,include_finance,include_public_data,fiscal_year,max_docs)

    old_status = U.council_status
    async def council_status(test_council: str = "광주 서구", live: bool = False) -> dict[str, Any]:
        result = await old_status(test_council=test_council,live=live)
        if not isinstance(result,dict):
            return result
        result["capacity"] = {"cache_entries_are_user_limits":False,
            "clik_cache_max_entries":U.CACHE_MAX,
            "short_result_cache":{"max_entries":CACHE_ENTRIES,"max_bytes":CACHE_BYTES,"ttl_seconds":CACHE_TTL,"current_entries":len(_CACHE)},
            "transport_max_concurrent":8,"tool_max_concurrent":3,"public_requests_per_minute":360,
            "metrics_since_restart":dict(METRICS),
            "note":"MCP 연결·도구목록 요청에는 전송 여유를 두고, 무거운 조회는 최대 3개씩 처리합니다. 캐시 확대가 외부 API 한도를 늘리지는 않습니다."}
        result["last_integration_validation"] = copy.deepcopy(_LAST_CHECK)
        result["client_requirements"] = {"public_tools":21,"authentication":"none","web_distribution":"existing eligible app reference","cross_account_access_guaranteed":False}
        for checked in result.get("live_checks",[]):
            if checked.get("check",{}).get("status") in {"ERROR","PARTIAL","NOT_CONFIGURED"}:
                result["status"] = "PARTIAL"
        return result

    old_session = U.council_session_ready_pack
    @functools.wraps(old_session)
    async def session(*args, **kwargs):
        result = await old_session(*args, **kwargs)
        if isinstance(result,dict):
            result["ready_for_submission"] = False
            for row in result.get("readiness",{}).get("audit_readiness_checklist",[]):
                if row.get("item") in {"법령·조례 근거","예산·집행 근거","관련 의안"} and row.get("status")=="CONFIRMED":
                    row["status"] = "CANDIDATE_FOUND"
            result["review_note"] = "자료 발견과 법적 적용·동일 사업·최신 수치 검증은 다릅니다."
        return result
    ann = inspect.get_annotations(old_session, eval_str=True)
    sig = inspect.signature(old_session)
    session.__signature__ = sig.replace(parameters=[p.replace(annotation=ann.get(p.name,p.annotation)) for p in sig.parameters.values()],return_annotation=ann.get("return",sig.return_annotation))
    session.__annotations__ = ann
    for name,fn in {"council_context_pack":council_context_pack,"council_status":council_status,"council_session_ready_pack":session}.items():
        setattr(U,name,fn)
        if U.profile_allows(name):
            from result_contract import wire_result
            try:
                U.mcp.remove_tool(name)
            except Exception:
                pass
            U.mcp.tool(name=name,annotations=U.RO)(wire_result(fn))
    U._v3_reliability_installed = True
