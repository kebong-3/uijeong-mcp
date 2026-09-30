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
    if isinstance(budget, (int, float)) and budget > 0 and isinstance(spent, (int, float)):
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
        "appropriated_amount": None,
        "unverified_fields": {"cpl_amt": row.get("cpl_amt")},
        "execution_rate_percent": rate,
    }


async def context(topic: str, council: str = "", fiscal_year: int | None = None,
                  limit: int = 20, search_terms: list[str] | None = None,
                  snapshot_date: str = "", budget_stage: str = "current") -> dict[str, Any]:
    """Use the same date-aware implementation in standalone and public paths."""
    from v3_reliability import finance_context
    return await finance_context(topic, council, fiscal_year, limit, search_terms,
                                 snapshot_date=snapshot_date, budget_stage=budget_stage)
