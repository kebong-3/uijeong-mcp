"""지방재정365 세부사업별 세출현황(QWGJK) evidence adapter.

Official dataset:
https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=0GAR4HBB8LWEBSL4NIHZ817053

The API uses a 지방재정365 OpenAPI key. The credential is never returned.
This adapter intentionally focuses on the single dataset most useful for
council budget/execution questions rather than exposing the full fiscal API
catalog to the model.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import os
import re
import time
from collections import OrderedDict
from typing import Any

import httpx

DATASET_URL = "https://www.lofin365.go.kr/portal/LF5120000.do?pdtaId=0GAR4HBB8LWEBSL4NIHZ817053"
KEY_APPLICATION_URL = "https://lofin.mois.go.kr/portal/user/openApi.do"
DEFAULT_ENDPOINT = "https://www.lofin365.go.kr/lf/hub/QWGJK"
SERVICE_CODE = "QWGJK"
PRIMARY_KEY_ENV = "LOFIN_API_KEY"
LEGACY_KEY_ENV = "FINANCE365_SERVICE_KEY"
URL_ENV = "FINANCE365_API_URL"

_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_CACHE_TTL = 300
_CACHE_MAX = 64
_SEM = asyncio.Semaphore(2)


class FinanceContextError(RuntimeError):
    pass


def _key() -> str:
    return (os.environ.get(PRIMARY_KEY_ENV, "").strip()
            or os.environ.get(LEGACY_KEY_ENV, "").strip())


def _endpoint() -> str:
    return os.environ.get(URL_ENV, "").strip() or DEFAULT_ENDPOINT


def configuration() -> dict[str, Any]:
    key = _key()
    return {
        "configured": bool(key),
        "service_code": SERVICE_CODE,
        "endpoint": _endpoint(),
        "dataset_url": DATASET_URL,
        "key_application_url": KEY_APPLICATION_URL,
        "env": {
            "primary_key": PRIMARY_KEY_ENV,
            "legacy_key": LEGACY_KEY_ENV,
            "api_url_override": URL_ENV,
        },
        "note": (
            "지방재정365 회원가입 후 OpenAPI 인증키를 발급받아 Render의 LOFIN_API_KEY에 입력합니다. "
            "FINANCE365_SERVICE_KEY는 기존 배포와의 호환용이며 새 설정에서는 LOFIN_API_KEY를 권장합니다."
        ),
    }


def _cache_key(params: dict[str, Any]) -> str:
    import hashlib
    safe = {k: v for k, v in params.items() if k != "Key"}
    raw = json.dumps(sorted((k, str(v)) for k, v in safe.items()),
                     ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _classify(code: str) -> tuple[bool, bool, bool]:
    code = str(code or "UNKNOWN").upper()
    if code == "INFO-000":
        return True, False, False
    if code == "INFO-200":
        return True, True, False
    numeric = code.split("-")[-1]
    if numeric in {"500", "600", "601"}:
        return False, False, True
    return False, False, False


def _parse_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FinanceContextError("LOFIN_UNEXPECTED_RESPONSE")

    # Some error/empty responses contain only RESULT at root.
    if SERVICE_CODE not in payload and "RESULT" in payload:
        result = payload.get("RESULT")
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            result = {}
        code = str(result.get("CODE") or "UNKNOWN")
        message = str(result.get("MESSAGE") or "")
        ok, empty, retryable = _classify(code)
        if ok:
            return {"result_code": code, "message": message, "total_count": 0, "rows": []}
        raise FinanceContextError(("LOFIN_RETRYABLE_" if retryable else "LOFIN_") + code)

    root = payload.get(SERVICE_CODE)
    if root is None:
        raise FinanceContextError("LOFIN_MISSING_SERVICE_ROOT")

    entries = root if isinstance(root, list) else [root]
    total = 0
    code = "UNKNOWN"
    message = ""
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        head = entry.get("head")
        if isinstance(head, dict):
            head = [head]
        if isinstance(head, list):
            for h in head:
                if not isinstance(h, dict):
                    continue
                if h.get("list_total_count") is not None:
                    try:
                        total = int(h.get("list_total_count") or 0)
                    except (TypeError, ValueError):
                        total = 0
                result = h.get("RESULT")
                if isinstance(result, list):
                    result = result[0] if result else {}
                if isinstance(result, dict):
                    code = str(result.get("CODE") or code)
                    message = str(result.get("MESSAGE") or message)
        found = entry.get("row")
        if isinstance(found, dict):
            found = [found]
        if isinstance(found, list):
            rows.extend(x for x in found if isinstance(x, dict))

    ok, empty, retryable = _classify(code)
    if not ok:
        raise FinanceContextError(("LOFIN_RETRYABLE_" if retryable else "LOFIN_") + code)
    return {
        "result_code": code,
        "message": message,
        "total_count": total,
        "rows": [] if empty else rows,
    }


async def _request(params: dict[str, Any]) -> dict[str, Any]:
    if not _key():
        raise FinanceContextError("LOFIN_API_KEY_NOT_CONFIGURED")

    complete = {
        "Key": _key(),
        "Type": "json",
        "pIndex": 1,
        "pSize": 1000,
        **{k: v for k, v in params.items() if v not in (None, "")},
    }
    ck = _cache_key(complete)
    cached = _CACHE.get(ck)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        _CACHE.move_to_end(ck)
        return copy.deepcopy(cached[1])

    last: Exception | None = None
    async with _SEM:
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=20,
                    follow_redirects=False,
                    headers={"User-Agent": "Uijeong-MCP/2.7 finance-context"},
                ) as client:
                    response = await client.get(_endpoint(), params=complete)
                if response.status_code >= 500 and attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                if response.status_code != 200:
                    raise FinanceContextError(f"LOFIN_HTTP_{response.status_code}")
                if len(response.content) > 8_000_000:
                    raise FinanceContextError("LOFIN_RESPONSE_TOO_LARGE")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise FinanceContextError("LOFIN_NON_JSON_RESPONSE") from exc
                parsed = _parse_payload(payload)
                _CACHE[ck] = (time.monotonic(), copy.deepcopy(parsed))
                _CACHE.move_to_end(ck)
                while len(_CACHE) > _CACHE_MAX:
                    _CACHE.popitem(last=False)
                return parsed
            except (httpx.TransportError, FinanceContextError) as exc:
                last = exc
                if attempt == 0 and ("RETRYABLE" in str(exc) or isinstance(exc, httpx.TransportError)):
                    await asyncio.sleep(0.5)
                    continue
                break
    raise FinanceContextError(str(last or "LOFIN_UNKNOWN_ERROR"))


async def ping() -> dict[str, Any]:
    """Validate the configured Finance365 key with one minimal QWGJK request.

    This does not prove a specific project exists; it only checks whether the
    upstream accepts the credential/request contract.
    """
    cfg = configuration()
    if not cfg["configured"]:
        return {"status": "NOT_CONFIGURED", "configured": False}
    today = dt.date.today()
    try:
        parsed = await _request({
            "fyr": str(today.year),
            "exe_ymd": today.strftime("%Y%m%d"),
        })
        return {
            "status": "COMPLETE",
            "configured": True,
            "service_code": SERVICE_CODE,
            "response_code": parsed["result_code"],
            "message": parsed["message"],
            "sample_rows_received": len(parsed["rows"]),
        }
    except FinanceContextError as exc:
        return {
            "status": "ERROR",
            "configured": True,
            "service_code": SERVICE_CODE,
            "message": str(exc),
        }


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).casefold()


def _council_aliases(council: str) -> set[str]:
    raw = _norm(str(council or "").replace("의회", ""))
    aliases = {raw} if raw else set()
    if "광주" in raw and "서구" in raw:
        aliases |= {
            _norm("광주서구"),
            _norm("광주광역시서구"),
            _norm("전남광주통합특별시서구"),
        }
    return {x for x in aliases if x}


def _belongs(row: dict[str, Any], council: str) -> bool:
    aliases = _council_aliases(council)
    if not aliases:
        return True
    name = _norm(row.get("laf_hg_nm"))
    return bool(name and any(a == name or a in name or name in a for a in aliases))


def _num(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").strip()
    try:
        n = float(text)
    except ValueError:
        return None
    return int(n) if n.is_integer() else n


def _snapshot_date(fiscal_year: int) -> str:
    today = dt.date.today()
    if fiscal_year > today.year:
        raise ValueError("미래 회계연도는 조회할 수 없습니다.")
    if fiscal_year == today.year:
        return today.strftime("%Y%m%d")
    return f"{fiscal_year}1231"


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    budget = _num(row.get("bdg_cash_amt"))
    spent = _num(row.get("ep_amt"))
    rate = None
    if isinstance(budget, (int, float)) and budget:
        rate = round((float(spent or 0) / float(budget)) * 100, 1)
    return {
        "fiscal_year": str(row.get("fyr") or ""),
        "execution_date": str(row.get("exe_ymd") or ""),
        "local_government": row.get("laf_hg_nm"),
        "local_government_code": str(row.get("laf_cd") or ""),
        "account": row.get("acnt_dv_nm"),
        "department_code": str(row.get("dept_cd") or ""),
        "project_code": str(row.get("dbiz_cd") or ""),
        "project_name": row.get("dbiz_nm"),
        "field": row.get("fld_nm"),
        "part": row.get("part_nm"),
        "budget_current_amount": budget,
        "national_fund": _num(row.get("bdg_ntep")),
        "province_fund": _num(row.get("capep")),
        "district_fund": _num(row.get("sggep")),
        "other_fund": _num(row.get("etc_amt")),
        "expenditure": spent,
        "appropriated_amount": _num(row.get("cpl_amt")),
        "execution_rate_percent": rate,
    }


async def context(topic: str, council: str = "", fiscal_year: int | None = None,
                  limit: int = 20, search_terms: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
        return {"status": "INVALID_INPUT", "message": "topic은 1~200자 문자열이어야 합니다."}
    if type(limit) is not int or not 1 <= limit <= 50:
        return {"status": "INVALID_INPUT", "message": "limit은 1~50입니다."}
    cfg = configuration()
    if not cfg["configured"]:
        return {
            "status": "NOT_CONFIGURED",
            "message": "지방재정365 OpenAPI 인증키가 아직 설정되지 않았습니다.",
            "configuration": cfg,
            "query": {"topic": topic, "council": council or None, "fiscal_year": fiscal_year},
            "items": [],
            "limitations": [
                "재정 API가 미설정이어도 CLIK·법령·조례 검색은 정상 작동합니다.",
                "지방재정365에서 OpenAPI 인증키를 발급받아 Render의 LOFIN_API_KEY에 입력하면 활성화됩니다.",
            ],
        }

    year = fiscal_year or dt.date.today().year
    terms = [topic.strip()]
    for term in (search_terms or []):
        if isinstance(term, str) and term.strip() and term.strip() not in terms and len(term.strip()) <= 100:
            terms.append(term.strip())
        if len(terms) >= 3:
            break
    try:
        exe_ymd = _snapshot_date(int(year))
        attempts = []
        combined_rows = []
        seen_rows = set()
        total_upstream = 0
        last_code = "INFO-200"
        last_message = ""
        for idx, term in enumerate(terms):
            parsed = await _request({
                "fyr": str(year),
                "dbiz_nm": term,
                "exe_ymd": exe_ymd,
            })
            last_code, last_message = parsed["result_code"], parsed["message"]
            total_upstream += int(parsed.get("total_count") or 0)
            matched_term = [row for row in parsed["rows"] if _belongs(row, council)] if council else parsed["rows"]
            attempts.append({"term": term, "upstream_total": parsed["total_count"],
                             "matched_local_government": len(matched_term),
                             "response_code": parsed["result_code"]})
            for row in matched_term:
                key = (str(row.get("laf_cd") or ""), str(row.get("dbiz_cd") or ""),
                       str(row.get("exe_ymd") or ""), str(row.get("acnt_dv_cd") or ""))
                if key not in seen_rows:
                    seen_rows.add(key)
                    combined_rows.append(row)
            if combined_rows:
                break  # progressive widening: exact or first successful synonym only
        parsed = {"rows": combined_rows, "total_count": total_upstream,
                  "result_code": last_code, "message": last_message}
    except (ValueError, FinanceContextError) as exc:
        return {
            "status": "ERROR" if not isinstance(exc, ValueError) else "INVALID_INPUT",
            "message": str(exc),
            "configuration": cfg,
            "query": {"topic": topic, "council": council or None, "fiscal_year": year},
            "items": [],
            "limitations": ["API 오류를 해당 사업의 예산·집행이 없다는 뜻으로 해석하지 마세요."],
        }

    rows = parsed["rows"]
    matched = rows
    items = [_public_row(row) for row in matched[:limit]]
    return {
        "status": "COMPLETE" if items else "EMPTY",
        "source": "행정안전부 지방재정365 세부사업별 세출현황",
        "service_code": SERVICE_CODE,
        "dataset_url": DATASET_URL,
        "query": {
            "topic": topic.strip(),
            "council": council or None,
            "fiscal_year": year,
            "snapshot_date": exe_ymd,
            "search_terms": terms,
        },
        "search_strategy": {
            "exact_first": True,
            "progressive_widening": len(attempts) > 1,
            "attempts": attempts,
            "rule": "정확 사업명 검색 후 미발견일 때만 보조어를 순차 검색하고, 첫 매칭에서 중단",
        },
        "upstream_total": parsed["total_count"],
        "matched_local_government_count": len(matched),
        "items": items,
        "coverage": {
            "response_code": parsed["result_code"],
            "message": parsed["message"],
            "p_size": 1000,
            "local_government_filter": sorted(_council_aliases(council)) if council else [],
        },
        "limitations": [
            "세부사업별 세출현황은 조회일 기준 일일자료입니다. 과거 회계연도는 12월 31일 스냅샷을 사용합니다.",
            "사업명 검색과 자치단체명 필터 결과이므로 세부사업명이 다른 동일·유사 사업은 누락될 수 있습니다.",
            "EMPTY는 이번 검색조건에서 미발견이라는 뜻이며 해당 사업 예산이 전혀 없다는 결론이 아닙니다.",
            "예산현액·지출액 등 금액의 최종 행정답변은 예산서·추경서·결산서와 담당부서 자료를 함께 확인하세요.",
        ],
    }
