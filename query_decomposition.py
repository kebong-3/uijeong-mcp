"""Deterministic Korean query decomposition for council/budget/ordinance workflows.

No model/API call is made here.  The goal is not semantic completeness; it is to
avoid passing an entire natural-language sentence directly into a narrow search
API and to make the chosen search terms inspectable by staff.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from term_core import extract_terms

_EXHAUSTIVE = ("모든", "전국 전체", "전수", "전수조사", "빠짐없이", "유사한 모든", "전체 사례")
_QUESTION_WORDS = {
    "찾아줘","찾아","비교해줘","비교","정리해줘","정리","검토해줘","검토","알려줘","관련","유사한",
    "전국","모든","전체","사례","조례","법령","근거","어떻게","무엇","뭐가","유의점","사항","설치","운영",
}
_LAW_PATTERNS = [
    re.compile(r"([가-힣A-Za-z0-9·s]{2,60}?(?:기본법|특별법|법률|법|시행령|시행규칙))(?=s|제d+조|에|의|을|를|,|.|$)")
]
_ARTICLE = re.compile(r"제s*(d+)s*조(?:의s*(d+))?")

# Function-oriented expansion.  These are search axes, not claims that the
# concepts are legally equivalent.
_AXES: tuple[tuple[str, tuple[str,...], tuple[str,...]], ...] = (
    ("ai", ("AI", "인공지능", "생성형 AI", "챗GPT", "ChatGPT", "업무자동화", "디지털 행정"),
     ("AI", "인공지능", "생성형 AI", "챗GPT", "업무자동화", "디지털 행정")),
    ("social_contribution", ("착한", "선한영향", "사회공헌", "나눔", "기부", "재능기부"),
     ("사회공헌", "나눔문화", "기부문화", "재능기부", "선한 영향력")),
    ("citizen_body", ("시민회의", "주민회의", "100인", "시민위원회", "주민참여단", "시민참여단", "자문단"),
     ("시민회의", "주민회의", "100인 위원회", "시민위원회", "주민참여단", "자문단", "협치")),
    ("deliberation", ("공론화", "숙의", "시민참여", "주민참여"),
     ("공론화", "숙의", "시민참여", "주민참여")),
    ("certification", ("인증", "인증표식", "예우"),
     ("인증", "사회공헌 인증", "인증취소", "예우")),
    ("incentive", ("포인트", "인센티브", "포상"),
     ("주민참여포인트", "시민참여포인트", "참여포인트", "인센티브", "포상")),
    ("employee_welfare", ("휴라운지", "휴게공간", "휴게실", "직원복지", "후생복지"),
     ("휴라운지", "직원 휴게공간", "휴게실", "직원 후생복지", "후생복지")),
)

def _norm(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).casefold()

def _unique(rows):
    out=[]
    for row in rows:
        row=re.sub(r"\s+"," ",str(row or "")).strip(" ,.;:/")
        if row and row not in out:
            out.append(row)
    return out

def _law_names(question: str) -> list[str]:
    out=[]
    for pattern in _LAW_PATTERNS:
        for match in pattern.findall(question):
            value=re.sub(r"\s+"," ",match).strip()
            # Strip leading question phrasing accidentally captured by the lazy pattern.
            for prefix in ("따라 ", "관련 ", "현행 ", "상위 "):
                if value.startswith(prefix):
                    value=value[len(prefix):]
            if 2 <= len(value) <= 60:
                out.append(value)
    # Prefer the shortest valid title when a pattern captures a leading phrase.
    cleaned=[]
    for value in out:
        words=value.split()
        for i in range(len(words)):
            candidate=" ".join(words[i:])
            if re.search(r"(기본법|특별법|법률|법|시행령|시행규칙)$",candidate):
                cleaned.append(candidate)
    cleaned=_unique(cleaned)
    cleaned.sort(key=len)
    return cleaned[:4]

def _articles(question: str) -> list[str]:
    out=[]
    for a,b in _ARTICLE.findall(question):
        out.append(f"제{a}조"+(f"의{b}" if b else ""))
    return _unique(out)

def _quoted_or_named_chunks(question: str) -> list[str]:
    chunks=[]
    for pattern in (r'["\\'“”‘’]([^"\\'“”‘’]{2,60})["\\'“”‘’]', r'([가-힣A-Za-z0-9]{2,20}(?:·[가-힣A-Za-z0-9]{2,20})+)'):
        for match in re.findall(pattern,question):
            chunks.extend(re.split(r"·|/|,",match))
    return [x.strip() for x in chunks if x.strip() and x.strip() not in _QUESTION_WORDS]

def functional_axes(question: str) -> list[dict[str,Any]]:
    n=_norm(question)
    rows=[]
    for axis,triggers,terms in _AXES:
        if any(_norm(t) in n for t in triggers):
            rows.append({"axis":axis,"triggered_by":[t for t in triggers if _norm(t) in n][:3],
                         "search_terms":list(terms)})
    return rows

def decompose(question: str, jurisdiction: str = "", max_terms: int = 6) -> dict[str,Any]:
    if not isinstance(question,str) or not question.strip() or len(question)>4000:
        raise ValueError("질문은 1~4000자 문자열이어야 합니다.")
    if type(max_terms) is not int or not 1<=max_terms<=12:
        raise ValueError("max_terms는 1~12입니다.")
    laws=_law_names(question)
    articles=_articles(question)
    axes=functional_axes(question)
    named=_quoted_or_named_chunks(question)
    core=[t for t in extract_terms(question) if t not in _QUESTION_WORDS and not any(_norm(t)==_norm(x) for x in laws)]
    generated=[]
    for row in axes:
        generated.extend(row["search_terms"])
    search_terms=_unique(named+generated+core)[:max_terms]
    exhaustive=any(term in question for term in _EXHAUSTIVE)
    return {
        "question":question.strip(),
        "jurisdiction":jurisdiction.strip(),
        "law_names":laws,
        "article_refs":articles,
        "named_policy_terms":named,
        "functional_axes":axes,
        "core_terms":core[:12],
        "search_terms":search_terms,
        "exhaustive_intent":exhaustive,
        "coverage_contract":{
            "query_terms_complete":False,
            "semantic_exhaustive":False,
            "national_exhaustive":False,
            "rule":("전수 요청을 감지했지만 검색어·API 연계범위가 의미상 전국 전수를 보장하지 않습니다."
                    if exhaustive else "생성된 검색어는 규칙 기반 후보이며 의미상 전체 표현을 보장하지 않습니다.")
        }
    }

def council_search_terms(question: str, max_terms: int = 3) -> list[str]:
    plan=decompose(question,max_terms=max(3,max_terms))
    terms=[question.strip()]
    # Multi-word generic questions often fail upstream; prefer functional/core terms
    # as fallbacks but keep the exact query first for traceability.
    for row in plan["functional_axes"]:
        terms.extend(row["search_terms"])
    terms.extend(plan["named_policy_terms"])
    terms.extend(plan["core_terms"])
    return _unique(terms)[:max_terms]

def legal_search_plan(question: str, jurisdiction: str = "", max_terms: int = 6) -> dict[str,Any]:
    plan=decompose(question,jurisdiction,max_terms)
    law_queries=plan["law_names"][:3]
    ordinance_queries=[]
    ordinance_queries.extend(plan["named_policy_terms"])
    for row in plan["functional_axes"]:
        ordinance_queries.extend(row["search_terms"])
    ordinance_queries.extend(plan["core_terms"])
    ordinance_queries=_unique(ordinance_queries)[:max_terms]
    if not law_queries and plan["core_terms"]:
        law_queries=plan["core_terms"][:2]
    return {**plan,"law_queries":law_queries,"ordinance_queries":ordinance_queries}
