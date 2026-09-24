"""Cross-source council context tools.

Adds three public-facing tools without expanding the raw API surface:
- council_legislation_context: national-law + ordinance evidence candidates
- council_finance_context: Finance365 readiness/context layer
- council_context_pack: council minutes/bills/member discovery/policy/law/finance join

CLIK member information is used only as a discovery index. Final statements
about speeches remain grounded in meeting minutes.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import finance_context as F
import legal_context as L
import runtime_security as R
from result_contract import wire_result

_TERMS_PATH = Path(__file__).parent / "data" / "administrative_terms.json"
try:
    _TERM_DATA = json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
    _TERM_MAP = _TERM_DATA.get("terms", {})
except (OSError, ValueError, TypeError):
    _TERM_MAP = {}


def _norm(value: str) -> str:
    import re
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _expansions(topic: str, limit: int = 2) -> list[str]:
    q = _norm(topic)
    out: list[str] = []
    for key, values in _TERM_MAP.items():
        k = _norm(key)
        if k and (k in q or q in k):
            for value in values:
                if value != topic and value not in out:
                    out.append(value)
                    if len(out) >= limit:
                        return out
    return out


def _jurisdiction_from_council(council_name: str) -> str:
    value = (council_name or "").replace("의회", "").strip()
    if value.startswith("전남광주통합특별시"):
        return value
    if "광주" in value and "서구" in value:
        return "전남광주통합특별시 서구"
    return value


def _member_item(row: dict[str, Any], via: str) -> dict[str, Any]:
    return {
        "member_name": row.get("ASEMBY_NM") or row.get("ASMBY_NM"),
        "council_name": row.get("RASMBLY_NM"),
        "docid": row.get("DOCID"),
        "matched_via": via,
        "role": "DISCOVERY_ONLY",
    }


async def _member_discovery(U: Any, topic: str, cid: str | None, limit: int = 6) -> dict[str, Any]:
    items, errors, seen = [], [], set()
    for search_type in ("SPKNG_CN", "BI_SJ"):
        try:
            obj = await U.clik.get(
                "assemblyinfo.do",
                displayType="list",
                startCount=0,
                listCount=max(1, min(20, limit)),
                searchType=search_type,
                searchKeyword=topic,
                rasmblyId=cid,
            )
            for row in U._rows(obj):
                docid = row.get("DOCID")
                if not docid or docid in seen:
                    continue
                seen.add(docid)
                items.append(_member_item(row, "회의발언내용" if search_type == "SPKNG_CN" else "발의의안"))
                if len(items) >= limit:
                    break
        except Exception as exc:
            errors.append({"source":"CLIK_ASSEMBLYINFO","search_type":search_type,
                           "message":R.safe_error(exc)})
        if len(items) >= limit:
            break
    return {
        "status":"PARTIAL" if errors and items else "ERROR" if errors and not items else "COMPLETE" if items else "EMPTY",
        "items":items,
        "errors":errors,
        "interpretation":"의원정보는 관련 공식기록 후보를 찾는 Discovery Index입니다. 실제 발언 인용은 회의록 원문으로 다시 확인해야 합니다.",
    }


async def _bill_context(U: Any, topic: str, cid: str | None, limit: int = 5) -> dict[str, Any]:
    try:
        obj = await U.clik.get(
            "bill.do", displayType="list", startCount=0, listCount=max(1,min(20,limit)),
            searchType="ALL", searchKeyword=topic, rasmblyId=cid, sort="ITNC_DE/DESC",
        )
        rows = U._rows(obj)[:limit]
    except Exception as exc:
        return {"status":"ERROR","items":[],"message":R.safe_error(exc)}
    if not rows:
        return {"status":"EMPTY","items":[]}
    details=[]
    for row in rows[:3]:
        docid=row.get("DOCID")
        if not docid:
            continue
        try:
            d=await U.clik.get("bill.do",displayType="detail",docid=docid)
            details.append({
                "docid":docid,
                "title":d.get("BI_SJ") or row.get("BI_SJ"),
                "kind":d.get("BI_KND_NM") or row.get("BI_KND_NM"),
                "proposal_date":d.get("ITNC_DE") or row.get("ITNC_DE"),
                "proposer":d.get("PROPSR"),
                "committee_result":d.get("CMIT_RESULT"),
                "plenary_result":d.get("PLNMT_RESULT_NM") or d.get("PLNMT_RESULT"),
                "promulgation_date":d.get("PRMLGT_DE"),
                "outline":U.re.sub(r"\s+"," ",U._html_to_marked_text(d.get("BI_OUTLINE","") or "").replace("\x01","").replace("\x02","")).strip()[:1200],
                "role":"OFFICIAL_BILL_RECORD",
            })
        except Exception:
            details.append({
                "docid":docid,"title":row.get("BI_SJ"),"kind":row.get("BI_KND_NM"),
                "proposal_date":row.get("ITNC_DE"),"role":"BILL_LIST_ONLY",
            })
    return {"status":"COMPLETE","items":details,"upstream_total":int(obj.get("TOTAL_COUNT") or 0)}


async def _policy_context(U: Any, topic: str, limit: int = 4) -> dict[str, Any]:
    try:
        obj=await U.clik.get("policyinfoList.do",startCount=0,listCount=max(1,min(20,limit)),
                             searchType="ALL",searchKeyword=topic)
        rows=U._rows(obj)[:limit]
    except Exception as exc:
        return {"status":"ERROR","items":[],"message":R.safe_error(exc)}
    if not rows:
        return {"status":"EMPTY","items":[]}
    out=[]
    for row in rows[:2]:
        docid=row.get("DOCID")
        if not docid:
            continue
        try:
            d=await U.clik.get("policyinfoDetail.do",docid=docid)
            out.append({
                "docid":docid,
                "title":d.get("TITLE") or row.get("TITLE"),
                "site":d.get("SITENM") or row.get("SITENM"),
                "type":d.get("SEEDNM") or row.get("SEEDNM"),
                "date":d.get("CDATE") or row.get("CDATE"),
                "url":d.get("URL"),
                "excerpt":U.re.sub(r"\s+"," ",U._html_to_marked_text(d.get("EXTRACTHTML","") or "").replace("\x01","").replace("\x02","")).strip()[:1000],
                "role":"BACKGROUND_ONLY",
            })
        except Exception:
            out.append({"docid":docid,"title":row.get("TITLE"),"site":row.get("SITENM"),
                        "type":row.get("SEEDNM"),"date":row.get("CDATE"),"role":"POLICY_LIST_ONLY"})
    return {"status":"COMPLETE","items":out,"upstream_total":int(obj.get("TOTAL_COUNT") or 0)}


def install(U: Any) -> None:
    """Attach extension functions to the existing backend.

    Core/work/private profiles keep their existing curated tool counts. The
    public launcher explicitly allowlists these new tools.
    """

    async def council_legislation_context(
        topic: str,
        council: str = "광주 서구",
        jurisdiction: Optional[str] = None,
        include_articles: bool = True,
    ) -> dict[str, Any]:
        """의회 대응에 필요한 상위법·자치법규 근거 후보를 조회합니다.
        검색 결과는 법적 결론이 아니라 공식 근거 후보이며, 최종 조례 제·개정 검토는 전문 입법검토가 필요합니다."""
        if not isinstance(topic,str) or not topic.strip() or len(topic)>200:
            return {"status":"INVALID_INPUT","message":"topic은 1~200자 문자열이어야 합니다."}
        cid,cname,error=U.pick_council(council)
        if error:
            return {"status":"INVALID_INPUT","message":error}
        wanted=jurisdiction or _jurisdiction_from_council(cname)
        result=await L.context(topic.strip(),wanted,include_articles=include_articles)
        result["council"]={"id":cid,"name":cname}
        result["usage_note"]="의회 답변의 법적 근거 후보 확인용입니다. 조문 적법성·위임범위·개정안 작성은 조례뿌시기 등 전문 입법검토에서 심화하세요."
        return result

    async def council_finance_context(
        topic: str,
        council: str = "광주 서구",
        fiscal_year: Optional[int] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """지방재정365 세부사업별 세출현황 연계 준비상태와 재정질의 컨텍스트를 확인합니다.
        현재는 승인받은 서비스키·요청 URL을 Render에 넣기 전까지 안전하게 NOT_CONFIGURED를 반환합니다."""
        cid,cname,error=U.pick_council(council)
        if error:
            return {"status":"INVALID_INPUT","message":error}
        result=await F.context(topic,cname,fiscal_year,limit)
        result["council"]={"id":cid,"name":cname}
        return result

    async def council_context_pack(
        topic: str,
        council: str = "광주 서구",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_legal: bool = True,
        include_finance: bool = True,
        max_docs: int = 4,
    ) -> dict[str, Any]:
        """한 현안의 의회기록·의안·의원공식기록후보·정책자료·법령/조례·재정상태를 한 번에 묶습니다.

        의원정보는 Discovery 전용이며 개인 성향·점수·순위를 만들지 않습니다.
        검색어 확장은 결과가 부족할 때만 보조어 최대 2개를 사용합니다.
        """
        if not isinstance(topic,str) or not topic.strip() or len(topic)>200:
            return {"status":"INVALID_INPUT","message":"topic은 1~200자 문자열이어야 합니다."}
        if type(max_docs) is not int or not 1<=max_docs<=6:
            return {"status":"INVALID_INPUT","message":"max_docs는 1~6입니다."}
        cid,cname,error=U.pick_council(council)
        if error:
            return {"status":"INVALID_INPUT","message":error}

        exact=await U.council_evidence_bundle(
            keyword=topic.strip(),council=council,mode="질의답변",
            date_from=date_from,date_to=date_to,max_docs=max_docs,source="auto",limit=8,
        )
        evidence=exact
        expansions=_expansions(topic,2)
        widened=False
        if expansions and isinstance(exact,dict) and (exact.get("status") in ("EMPTY","ERROR") or int(exact.get("total_items") or 0)<2):
            widened=True
            evidence=await U.council_evidence_bundle(
                keyword=topic.strip(),council=council,mode="질의답변",
                date_from=date_from,date_to=date_to,max_docs=max_docs,source="auto",
                search_terms=expansions,limit=8,
            )

        member_task=_member_discovery(U,topic.strip(),cid,6)
        bill_task=_bill_context(U,topic.strip(),cid,5)
        policy_task=_policy_context(U,topic.strip(),4)
        tasks=[member_task,bill_task,policy_task]
        if include_legal:
            tasks.append(L.context(topic.strip(),_jurisdiction_from_council(cname),include_articles=True))
        if include_finance:
            tasks.append(F.context(topic.strip(),cname,None,20))
        results=await asyncio.gather(*tasks)

        idx=0
        members=results[idx];idx+=1
        bills=results[idx];idx+=1
        policy=results[idx];idx+=1
        legal=results[idx] if include_legal else {"status":"SKIPPED"}; idx += 1 if include_legal else 0
        finance=results[idx] if include_finance else {"status":"SKIPPED"}

        statuses=[
            evidence.get("status") if isinstance(evidence,dict) else "ERROR",
            members.get("status"),bills.get("status"),policy.get("status"),
            legal.get("status"),finance.get("status"),
        ]
        completed=[x for x in statuses if x in ("COMPLETE","EMPTY","NOT_CONFIGURED","SKIPPED","PENDING_ENDPOINT_CONTRACT")]
        status="COMPLETE" if len(completed)==len(statuses) and (evidence.get("status") if isinstance(evidence,dict) else "ERROR")!="ERROR" else "PARTIAL"

        return {
            "status":status,
            "topic":topic.strip(),
            "council":{"id":cid,"name":cname},
            "search_strategy":{
                "exact_first":True,
                "expanded":widened,
                "expansions":expansions if widened else [],
                "rule":"보조 검색어는 원질문 결과가 부족할 때만 최대 2개 사용",
            },
            "council_evidence":evidence,
            "related_bills":bills,
            "member_record_discovery":members,
            "policy_background":policy,
            "legal_and_ordinance_context":legal,
            "finance_context":finance,
            "interpretation":[
                "회의록은 최종 발언 근거, 의원정보는 관련 공식기록 후보 발견용입니다.",
                "법령·조례 결과는 의회 대응용 근거 후보이며 최종 법적 판단은 별도 전문 검토가 필요합니다.",
                "재정 API가 미설정이어도 나머지 레이어는 정상 반환됩니다.",
                "ERROR를 자료 없음으로 해석하지 않으며 PARTIAL은 확인 범위를 함께 표시해야 합니다.",
            ],
        }

    for fn in (council_legislation_context,council_finance_context,council_context_pack):
        setattr(U,fn.__name__,fn)
        if U.profile_allows(fn.__name__):
            try:
                U.mcp.remove_tool(fn.__name__)
            except Exception:
                pass
            U.mcp.tool(name=fn.__name__,annotations=U.RO)(wire_result(fn))
