"""Bounded date-aware fiscal lookup. Current funds never establish an adopted budget."""
from __future__ import annotations
import datetime as dt
import re
import time
from decimal import Decimal

DATASET_URL = "https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=0GAR4HBB8LWEBSL4NIHZ817053"
CATALOG_URL = "https://www.data.go.kr/data/15138857/openapi.do"
STAGES = {"current": "조회일 예산현액", "original": "의결된 본예산", "supplementary": "의결된 추경",
          "draft": "제출 예산안", "settlement": "확정 결산"}
MAX_SECONDS = 25
MAX_REQUESTS = 10
MAX_DATE_LOOKBACK = 7
MAX_TERMS = 4

def search_candidates(topic, extras, normalize):
    from query_decomposition import search_synonyms
    from query_decomposition import split_budget_terms
    core_terms = split_budget_terms(topic)
    terms = [(core_terms[0], "EXACT_TEXT")]
    terms += [(term, "TERMINOLOGY_SYNONYM") for term in core_terms[1:] + search_synonyms(core_terms[0])]

    compact = re.sub(r"[\s·,，ㆍ()（）]", "", topic.strip())
    if len(core_terms) == 1 and compact != topic.strip():
        terms.append((compact, "SPELLING_VARIANT"))
    if "세큰대" in normalize(topic) or "세상에서가장큰대학" in normalize(topic):
        terms.append(("세상에서", "BRAND_CANDIDATE"))
    for term in extras:
        if isinstance(term, str) and term.strip():
            terms.append((term.strip(), "RELATED_TERM"))
    result, seen = [], set()
    for term, kind in terms:
        if term not in seen and len(term) <= 200:
            result.append((term, kind))
            seen.add(term)
        if len(result) >= MAX_TERMS:
            break
    return result

def fiscal_basis(stage, date, evidence_found=False):
    return {"requested_stage": stage, "requested_stage_label": STAGES[stage],
        "returned_stage": "current", "returned_stage_label": STAGES["current"],
        "requested_stage_supported": stage == "current",
        "requested_stage_verified": stage == "current" and evidence_found,
        "amount_verified": False, "same_project_verified": False, "basis_date": date,
        "amount_unit": "SOURCE_CONFIRMATION_REQUIRED",
        "field_meanings": {"budget_current_amount": "bdg_cash_amt: 조회일 예산현액",
                          "expenditure": "ep_amt: 조회일 기준 지출액",
                          "cpl_amt": "필드 의미 미검증. 본예산·확정예산으로 사용 금지"},
        "document_checks": ["의결된 본예산서", "해당 추경 예산서", "결산서(결산 질문 시)"],
        "rules": ["회의록의 예산안 설명액은 의결된 최종 본예산의 증거가 아닙니다.",
                  "조회일 예산현액에는 변경·이월 등이 반영될 수 있어 본예산과 같다고 가정하지 않습니다.",
                  "사업코드·지자체·회계·연도를 대조하기 전 관련 사업을 합산하지 않습니다.",
                  "사업의 국비·시도비·구비는 재원 구성이며 지자체 전체 세입명세가 아닙니다.",
                  "단위는 공식 명세·예산서에서 확인한 뒤 원·천원·백만원을 변환합니다."]}

def row_evidence(row, adapter, term, kind):
    item = adapter._public_row(row)
    from evidence_quality import fiscal_unit_contract
    item.update({k:v for k,v in fiscal_unit_contract().items() if k in ("unit_verified", "unit_source", "numeric_display_policy", "numeric_normalization")})
    item.update(appropriated_amount=None, unverified_fields={"cpl_amt": row.get("cpl_amt")},
                budget_stage="current", amount_unit="SOURCE_CONFIRMATION_REQUIRED",
                matched_query=term, same_project_verified=False)
    item["match_status"] = ("SPELLING_MATCH_CANDIDATE" if kind == "SPELLING_VARIANT" else
        "PROJECT_NAME_MATCH_CANDIDATE" if kind == "EXACT_TEXT" else "RELATED_PROJECT_CANDIDATE")
    budget, spent = item.get("budget_current_amount"), item.get("expenditure")
    balance = Decimal(str(budget)) - Decimal(str(spent)) if budget is not None and spent is not None else None
    item["unspent_current_amount"] = (int(balance) if balance == balance.to_integral_value() else str(balance)) if balance is not None else None
    item["source_link"] = {"url": DATASET_URL, "label": "지방재정365 세부사업별 세출현황(공식 데이터셋)",
        "kind": "OFFICIAL_DATASET", "status": "DATASET_REFERENCE", "direct_document": False,
        "markdown": f"[지방재정365 세부사업별 세출현황]({DATASET_URL})",
        "lookup": {k: item.get(k) for k in ("fiscal_year", "execution_date", "local_government",
                  "local_government_code", "account", "project_name", "project_code")},
        "note": "데이터셋 안내 링크입니다. 특정 사업 예산서 원문이 아닙니다. 조회조건으로 대조하세요."}
    return item

async def context(topic, council, fiscal_year, limit, search_terms, snapshot_date, budget_stage, adapter, reliability):
    F, V = adapter, reliability
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200 or type(limit) is not int or not 1 <= limit <= 50:
        return {"status": "INVALID_INPUT", "items": []}
    year = V.today().year if fiscal_year is None else fiscal_year
    if type(year) is not int or not 2016 <= year <= V.today().year:
        return {"status": "INVALID_INPUT", "message": "회계연도는 2016년부터 현재연도 사이입니다.", "items": []}
    if not isinstance(budget_stage, str) or budget_stage not in STAGES:
        return {"status": "INVALID_INPUT", "message": "예산 단계를 확인하세요.", "items": []}
    if search_terms is not None and (not isinstance(search_terms, list) or any(not isinstance(t, str) or len(t) > 100 for t in search_terms)):
        return {"status": "INVALID_INPUT", "items": []}
    try:
        requested = V.today() if year == V.today().year else dt.date(year, 12, 31)
        if snapshot_date:
            if not isinstance(snapshot_date, str) or not re.fullmatch(r"\d{4}-?\d{2}-?\d{2}", snapshot_date):
                raise ValueError
            requested = dt.datetime.strptime(snapshot_date.replace("-", ""), "%Y%m%d").date()
            if requested.year != year or requested > V.today():
                raise ValueError
    except (TypeError, ValueError):
        return {"status": "INVALID_INPUT", "message": "기준일은 해당 회계연도의 오늘 이전 YYYY-MM-DD/ YYYYMMDD입니다.", "items": []}
    if not F.configuration()["configured"]:
        return {"status": "NOT_CONFIGURED", "configuration": F.configuration(), "items": []}
    started, requests = time.monotonic(), 0
    errors, attempts, date_attempts, found = [], [], [], []
    incomplete, used_date = False, None
    seen = set()
    extras = search_terms if search_terms is not None else V.expansions(topic, "finance")
    terms = search_candidates(topic, extras, V.norm)
    union_queries = {term for term, kind in terms if kind in ("EXACT_TEXT", "TERMINOLOGY_SYNONYM")}
    use_union = any(kind == "TERMINOLOGY_SYNONYM" for _, kind in terms)
    planned_queries = [term for term, _ in terms]
    requested_search_terms = list(dict.fromkeys(term.strip() for term in extras
                                                if isinstance(term, str) and term.strip()))
    omitted_search_terms = [term for term in requested_search_terms if term not in planned_queries]
    async def request(params):
        nonlocal requests
        remaining = MAX_SECONDS - (time.monotonic() - started)
        if remaining < 0.2 or requests >= MAX_REQUESTS:
            return {"status": "ERROR", "code": "FINANCE_LOOKUP_BUDGET", "message": "조회 범위에 도달했습니다. 날짜·사업명을 좁혀 재조회하세요."}
        requests += 1
        return await V.stage(F._request(params), min(10, remaining))
    # Date availability is independent of project terms. Never look backwards
    # simply because a project does not match the latest available snapshot.
    for days in range(MAX_DATE_LOOKBACK + 1):
        candidate = requested - dt.timedelta(days=days)
        if candidate.year != year:
            break
        date = candidate.strftime("%Y%m%d")
        parsed = await request({"fyr": str(year), "exe_ymd": date, "pSize": 1})
        if parsed.get("status") == "ERROR":
            errors.append({"stage": "date_availability", "snapshot_date": date, **parsed})
            break
        available = bool(parsed.get("rows")) and int(parsed.get("total_count") or 0) > 0
        date_attempts.append({"snapshot_date": date, "data_available": available, "response_code": parsed.get("result_code")})
        if available:
            used_date = date
            break
    if used_date:
        for term, kind in terms:
            parsed = await request({"fyr": str(year), "dbiz_nm": term, "exe_ymd": used_date, "pSize": 1000})
            if parsed.get("status") == "ERROR":
                errors.append({"stage": "project_search", "term": term, **parsed})
                break
            rows = parsed.get("rows", [])
            total = int(parsed.get("total_count") or 0)
            incomplete |= total > len(rows)
            local = [r for r in rows if V.finance_belongs(r, council) and str(r.get("fyr") or "") == str(year)
                     and str(r.get("exe_ymd") or "") == used_date]
            attempts.append({"term": term, "match_kind": kind, "snapshot_date": used_date, "upstream_total": total,
                             "rows_received": len(rows), "matched_local_government": len(local), "response_code": parsed.get("result_code")})
            for row in local:
                key = (str(row.get("laf_cd")), str(row.get("dbiz_cd")), str(row.get("acnt_dv_cd") or row.get("acnt_dv_nm")))
                if key not in seen:
                    seen.add(key)
                    found.append(row_evidence(row, F, term, kind))
            if found and (not use_union or union_queries <= {a["term"] for a in attempts}):
                break
    stage_incomplete = bool(found and budget_stage != "current")
    status = ("ERROR" if errors and not found and not attempts else "PARTIAL"
              if errors or incomplete or omitted_search_terms or len(found) > limit or stage_incomplete else "COMPLETE" if found else "EMPTY")
    result = {"status": status, "source": "행정안전부 지방재정365 세부사업별 세출현황",
        "service_code": F.SERVICE_CODE, "dataset_url": DATASET_URL, "source_url": CATALOG_URL,
        "query": {"topic": topic.strip(), "council": council, "fiscal_year": year,
                  "requested_snapshot_date": requested.strftime("%Y%m%d"), "snapshot_date": used_date, "budget_stage": budget_stage},
        "items": found[:limit], "upstream_total": sum(a["upstream_total"] for a in attempts), "matched_local_government_count": len(found),
        "date_resolution": {"strategy": "LATEST_AVAILABLE_ON_OR_BEFORE_REQUESTED",
            "fallback_used": bool(used_date and used_date != requested.strftime("%Y%m%d")), "date_attempts": date_attempts,
            "max_lookback_days": MAX_DATE_LOOKBACK, "mixed_dates": False},
        "search_strategy": {"exact_first": True, "progressive_widening": len(attempts) > 1,
            "requested_search_terms": requested_search_terms, "planned_queries": planned_queries,
            "omitted_search_terms": omitted_search_terms, "max_search_expressions": MAX_TERMS,
            "omission_reason": "SEARCH_EXPRESSION_LIMIT" if omitted_search_terms else None,
            "unattempted_queries": [term for term in planned_queries if term not in {a["term"] for a in attempts}],
            "combination": "BOUNDED_SYNONYM_UNION" if use_union else "BOUNDED_FALLBACK",
            "identity_basis": ["local_government_code", "fiscal_year", "execution_date", "account", "project_code"],
            "stop_reason": "SYNONYM_UNION_COMPLETE" if found and use_union and union_queries <= {a["term"] for a in attempts} else "FIRST_CANDIDATE_FOUND" if found else "UPSTREAM_OR_LOOKUP_LIMIT" if errors else
                           "NO_AVAILABLE_SNAPSHOT" if not used_date else "PLANNED_SEARCH_COMPLETE",
            "attempts": attempts, "request_count": requests},
        "budget_basis": fiscal_basis(budget_stage, used_date, bool(found)),
        "coverage": {"limited": bool(errors or incomplete or omitted_search_terms or len(found) > limit or stage_incomplete), "is_exhaustive": False,
            "search_terms_omitted": bool(omitted_search_terms),
            "scanned_pages_per_query": 1, "has_unread_pages": incomplete, "date_data_available": bool(used_date),
            "requested_stage_complete": bool(found) and not stage_incomplete},
        "errors": errors, "configured": True,
        "answer_guidance": ["결론에 실제 반환된 예산 단계와 기준일을 표시하세요.",
            "각 수치 뒤에 source_links 또는 source_link의 markdown을 붙이세요.",
            "데이터셋 링크를 특정 사업 예산서 원문 링크라고 소개하지 마세요.",
            "requested_stage_verified가 false이면 요청한 본예산·추경·예산안·결산 금액은 미확인이라고 표시하세요."],
        "limitations": ["미발견·날짜 미제공·조회 오류는 예산 없음이나 0원이 아닙니다.",
            "같은 기준일의 사업·회계별 행만 반환합니다. 다른 날짜나 관련 사업을 자동 합산하지 않습니다.",
            "단위·확정 본예산·추경·결산은 공식 명세·예산서에서 대조하세요.",
            "전국 첫 1,000건만 확인했으면 누락 가능성을 PARTIAL로 표시합니다."]}
    from evidence_quality import fiscal_unit_contract
    result["unit_metadata"] = fiscal_unit_contract()
    result["numeric_normalization"] = "BLOCK_NUMERIC_NORMALIZATION"
    result["answer_guidance"].append("금액 단위가 공식 확인되지 않았으므로 '단위 미검증 원시값'이라고 표시하고 원/천원 환산·합산은 하지 마세요.")
    V._LAST_CHECK["finance365"] = {"status": status, "items": len(found), "snapshot_date": used_date, "checked_at": dt.datetime.now(V.KST).isoformat()}
    return result
