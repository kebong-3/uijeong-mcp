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
import public_data_discovery as D
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
        """지방재정365 세부사업별 세출현황에서 예산현액·재원구성·지출액·집행률을 조회합니다.
        검색 미발견과 API 오류를 구분하며 최종 예산답변은 공식 예산서·추경서·결산서 확인이 필요합니다."""
        cid,cname,error=U.pick_council(council)
        if error:
            return {"status":"INVALID_INPUT","message":error}
        result=await F.context(topic,cname,fiscal_year,limit,search_terms=_expansions(topic,2))
        result["council"]={"id":cid,"name":cname}
        result["execution_trace"]={"mcp_tool":"council_finance_context","source":"FINANCE365","used":True}
        return result

    async def council_context_pack(
        topic: str,
        council: str = "광주 서구",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_legal: bool = True,
        include_finance: bool = True,
        include_public_data: bool = False,
        fiscal_year: Optional[int] = None,
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
            tasks.append(F.context(topic.strip(),cname,fiscal_year,20,search_terms=_expansions(topic,2)))
        if include_public_data:
            tasks.append(D.search(topic.strip(),6))
        results=await asyncio.gather(*tasks)

        idx=0
        members=results[idx];idx+=1
        bills=results[idx];idx+=1
        policy=results[idx];idx+=1
        legal=results[idx] if include_legal else {"status":"SKIPPED"}; idx += 1 if include_legal else 0
        finance=results[idx] if include_finance else {"status":"SKIPPED"}; idx += 1 if include_finance else 0
        public_data=results[idx] if include_public_data else {"status":"SKIPPED"}

        statuses=[
            evidence.get("status") if isinstance(evidence,dict) else "ERROR",
            members.get("status"),bills.get("status"),policy.get("status"),
            legal.get("status"),finance.get("status"),public_data.get("status"),
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
            "public_data_discovery":public_data,
            "execution_trace":{
                "mcp_tool":"council_context_pack",
                "stages":[
                    {"stage":"council_evidence","source":"CLIK/official council site","status":evidence.get("status") if isinstance(evidence,dict) else "ERROR"},
                    {"stage":"related_bills","source":"CLIK bill","status":bills.get("status")},
                    {"stage":"member_discovery","source":"CLIK assemblyinfo","status":members.get("status"),"role":"DISCOVERY_ONLY"},
                    {"stage":"policy_background","source":"CLIK policyinfo","status":policy.get("status"),"role":"BACKGROUND_ONLY"},
                    {"stage":"legal","source":"National Law Information","status":legal.get("status")},
                    {"stage":"finance","source":"Finance365","status":finance.get("status")},
                    {"stage":"public_data_discovery","source":"data.go.kr search","status":public_data.get("status"),"role":"DISCOVERY_ONLY"}
                ],
                "supplemental_web_search_required": any(x in ("ERROR","PARTIAL") for x in statuses)
            },
            "integration_configuration":{
                "law":L.configuration(),
                "finance365":F.configuration(),
                "public_data_search":D.configuration(),
            },
            "interpretation":[
                "회의록은 최종 발언 근거, 의원정보는 관련 공식기록 후보 발견용입니다.",
                "법령·조례 결과는 의회 대응용 근거 후보이며 최종 법적 판단은 별도 전문 검토가 필요합니다.",
                "재정·공공데이터 검색 API가 미설정이어도 나머지 레이어는 정상 반환됩니다.",
                "공공데이터 검색 결과는 데이터값이 아니라 추가 공식 데이터 후보입니다. 자동으로 후보 API를 실행하지 않습니다.",
                "ERROR를 자료 없음으로 해석하지 않으며 PARTIAL은 확인 범위를 함께 표시해야 합니다.",
            ],
        }

    PURPOSES = {"일반","업무보고","행정사무감사","본예산","추경","조례·의안","5분발언","구정질문"}

    async def council_session_ready_pack(
        topic: str,
        council: str = "광주 서구",
        purpose: str = "일반",
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        fiscal_year: Optional[int] = None,
        need_public_data: bool = False,
        max_docs: int = 4,
    ) -> dict[str, Any]:
        """회기 전 실무 준비용 시그니처 도구입니다.

        회의록·의안·법령/조례·재정 근거를 목적에 맞게 묶고, 동일 스냅샷으로 답변준비자료를 생성합니다.
        purpose: 일반 | 업무보고 | 행정사무감사 | 본예산 | 추경 | 조례·의안 | 5분발언 | 구정질문
        need_public_data=True일 때만 공공데이터포털에서 추가 데이터 후보를 탐색합니다.
        """
        if purpose not in PURPOSES:
            return {"status":"INVALID_INPUT","message":"지원 purpose: "+", ".join(sorted(PURPOSES))}
        if not isinstance(topic,str) or not topic.strip() or len(topic)>200:
            return {"status":"INVALID_INPUT","message":"topic은 1~200자 문자열이어야 합니다."}

        finance_cues=("예산","추경","결산","집행","사업비","재원","국비","시비","구비")
        finance_needed = purpose in {"본예산","추경","행정사무감사"} or any(x in topic for x in finance_cues)
        legal_needed = purpose in {"조례·의안","본예산","추경","행정사무감사","구정질문"} or any(
            x in topic for x in ("조례","법령","법적근거","상위법","위임","동의안","민간위탁","출연")
        )

        context = await council_context_pack(
            topic=topic,council=council,date_from=date_from,date_to=date_to,
            include_legal=legal_needed,include_finance=finance_needed,
            include_public_data=need_public_data,fiscal_year=fiscal_year,max_docs=max_docs,
        )
        if context.get("status")=="INVALID_INPUT":
            return context

        evidence=context.get("council_evidence") if isinstance(context,dict) else None
        snapshot=(evidence or {}).get("snapshot_id") if isinstance(evidence,dict) else None
        # council_prepare_pack의 snapshot 재사용은 동일 검색조건일 때만 안전하다.
        # 보조 검색어가 추가된 경우에는 exact 검색으로 준비팩을 다시 만들고, 확장 근거는 context에 보존한다.
        reuse_snapshot = snapshot if not context.get("search_strategy",{}).get("expanded") else None
        prepared=await U.council_prepare_pack(
            keyword=topic,council=council,date_from=date_from,date_to=date_to,
            max_docs=max_docs,snapshot_id=reuse_snapshot,max_evidence=10,
        )

        source_status={
            "council_evidence":(evidence or {}).get("status") if isinstance(evidence,dict) else "ERROR",
            "bills":context.get("related_bills",{}).get("status"),
            "legal":context.get("legal_and_ordinance_context",{}).get("status"),
            "finance":context.get("finance_context",{}).get("status"),
            "public_data_discovery":context.get("public_data_discovery",{}).get("status"),
            "response_pack":prepared.get("status") if isinstance(prepared,dict) else "ERROR",
        }
        gaps=[]
        for key,value in source_status.items():
            if value in ("ERROR","PARTIAL","NOT_CONFIGURED"):
                gaps.append({"area":key,"status":value})
        next_tools=[]
        if purpose in {"행정사무감사","업무보고"}:
            next_tools.append({"tool":"council_recurring_issues","why":"여러 회의연도의 반복 쟁점 후보를 별도로 확인"})
        if purpose in {"본예산","추경"}:
            next_tools.append({"tool":"council_finance_context","why":"특정 세부사업명·회계연도를 좁혀 재정 수치를 재확인"})
        if purpose=="조례·의안":
            next_tools.append({"tool":"council_legislation_context","why":"상위법·자치법규 조문 후보를 재확인"})

        coverage_card={
            "requested_scope":{"topic":topic.strip(),"council":context.get("council"),"date_from":date_from,"date_to":date_to,
                               "purpose":purpose,"fiscal_year":fiscal_year},
            "search_strategy":context.get("search_strategy",{}),
            "source_status":source_status,
            "evidence_status":(evidence or {}).get("status") if isinstance(evidence,dict) else "ERROR",
            "checked_not_proven_absent":True,
            "interpretation":"미발견은 확인한 기간·검색어·출처 범위에 한정하며 전체 부재를 의미하지 않습니다."
        }

        def check_item(name, status, basis, action=None):
            row={"item":name,"status":status,"basis":basis}
            if action: row["action"]=action
            return row

        legal_items=(context.get("legal_and_ordinance_context",{}).get("laws") or []) + (context.get("legal_and_ordinance_context",{}).get("ordinances") or [])
        finance_items=context.get("finance_context",{}).get("items") or []
        council_items=(evidence or {}).get("items") or [] if isinstance(evidence,dict) else []
        bill_items=context.get("related_bills",{}).get("items") or []
        followup_entries=(prepared.get("followup_ledger",{}).get("entries") or []) if isinstance(prepared,dict) else []
        audit_readiness=[
            check_item("과거 의회 질의·답변", "CONFIRMED" if council_items else "NEEDS_CONFIRMATION",
                       f"공식 근거 {len(council_items)}건 확인" if council_items else "이번 검색에서 직접 연결된 질의·답변 미확인",
                       None if council_items else "검색어·기간·회의유형 확장 여부 검토"),
            check_item("관련 의안", "CONFIRMED" if bill_items else "NOT_OBSERVED_IN_SEARCH",
                       f"관련 의안 후보 {len(bill_items)}건" if bill_items else "이번 검색범위에서 관련 의안 미확인"),
            check_item("법령·조례 근거", "CONFIRMED" if legal_items else ("NOT_CONFIGURED" if source_status.get("legal")=="NOT_CONFIGURED" else "NEEDS_CONFIRMATION"),
                       f"법령·자치법규 후보 {len(legal_items)}건" if legal_items else "법적 근거 후보 추가 확인 필요",
                       "시행일·부칙·위임범위 원문 확인"),
            check_item("예산·집행 근거", "CONFIRMED" if finance_items else ("NOT_CONFIGURED" if source_status.get("finance")=="NOT_CONFIGURED" else "NEEDS_CONFIRMATION"),
                       f"지방재정365 관련 세부사업 후보 {len(finance_items)}건" if finance_items else "세부사업명 불일치 가능성 포함 추가 확인 필요",
                       "공식 예산서·추경서·결산서와 최종 대조"),
            check_item("과거 후속조치 후보", "CANDIDATE_FOUND" if followup_entries else "NOT_OBSERVED_IN_SEARCH",
                       f"후속조치 후보 {len(followup_entries)}건" if followup_entries else "이번 확인 범위에서 후속조치 후보 미확인",
                       "실제 이행상태는 담당부서 증빙 확인"),
            check_item("현재 사업현황·최근 실적", "DEPARTMENT_CONFIRMATION_REQUIRED",
                       "공개 의회·법령·재정 데이터만으로 현재 내부 실적을 확정할 수 없음",
                       "최신 내부 업무자료 확인"),
            check_item("이용률·참여율·대상자 현황", "DEPARTMENT_CONFIRMATION_REQUIRED",
                       "사업별 운영실적은 별도 행정자료가 필요할 수 있음",
                       "월별·연도별 실적표 준비"),
            check_item("만족도·민원·개선요구", "DEPARTMENT_CONFIRMATION_REQUIRED",
                       "공개 회의록 검색만으로 현재 만족도·민원현황을 확정할 수 없음",
                       "설문·민원·개선조치 자료 확인"),
            check_item("본청·현장·부서 간 접근 형평성", "DEPARTMENT_CONFIRMATION_REQUIRED",
                       "사업 대상·접근성의 현재 운영상태 확인 필요",
                       "대상별 이용조건·대체지원 확인"),
            check_item("향후계획·답변수치", "DEPARTMENT_CONFIRMATION_REQUIRED",
                       "향후계획과 최신 수치는 정책결정·담당부서 확인사항",
                       "결재자료와 수치 최종 검증")
        ]
        return {
            "status":"PARTIAL" if gaps else context.get("status","PARTIAL"),
            "workflow":"SESSION_READY_PACK",
            "purpose":purpose,
            "topic":topic.strip(),
            "council":context.get("council"),
            "context":context,
            "response_preparation":prepared,
            "coverage_card":coverage_card,
            "execution_trace":{
                "mcp_tool":"council_session_ready_pack",
                "mcp_first":True,
                "sources_used":[k for k,v in source_status.items() if v not in (None,"SKIPPED","NOT_CONFIGURED")],
                "supplemental_web_search_policy":"MCP 근거 우선. 부족한 범위만 공식 웹검색으로 보완하고 보완검색임을 표시."
            },
            "readiness":{
                "source_status":source_status,
                "gaps":gaps,
                "human_checklist":[
                    "현재 사업현황·최근 실적이 최신 내부자료와 일치하는지 확인",
                    "의회에 과거 답변한 후속조치의 실제 이행상태 확인",
                    "예산·추경·결산 수치는 공식 예산서와 담당부서 자료로 최종 대조",
                    "법령·조례 후보는 시행일·부칙·위임범위까지 원문으로 최종 확인",
                    "답변 초안의 수치·고유명사·기한은 담당자가 최종 검증",
                ],
                "recommended_followup_tools":next_tools,
                "audit_readiness_checklist":audit_readiness if purpose=="행정사무감사" else audit_readiness[:5],
            },
            "signature_note":"의회기록→법령·조례→예산·집행→답변준비 순으로 근거를 연결하는 공무원용 회기 대비 패키지",
        }

    base_status=U.council_status
    async def council_status(test_council:str="광주 서구",live:bool=False)->dict[str, Any]:
        result=await base_status(test_council=test_council,live=live)
        if not isinstance(result,dict):
            return result
        result["integrations"]={
            "law":L.configuration(),
            "finance365":F.configuration(),
            "public_data_search":D.configuration(),
        }
        if live and F.configuration().get("configured"):
            result.setdefault("live_checks",[]).append({"source":"FINANCE365","check":await F.ping()})
            if result["live_checks"][-1]["check"].get("status")=="ERROR":
                result["status"]="PARTIAL"
        if live and D.configuration().get("configured"):
            result.setdefault("live_checks",[]).append({"source":"DATA_GO_KR_SEARCH","check":await D.search("지방행정",1)})
        return result

    setattr(U,"council_status",council_status)

    for fn in (council_legislation_context,council_finance_context,council_context_pack,council_session_ready_pack):
        setattr(U,fn.__name__,fn)
        if U.profile_allows(fn.__name__):
            try:
                U.mcp.remove_tool(fn.__name__)
            except Exception:
                pass
            U.mcp.tool(name=fn.__name__,annotations=U.RO)(wire_result(fn))
