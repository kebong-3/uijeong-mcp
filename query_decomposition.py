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
from jurisdiction_identity import resolve_jurisdiction

_EXHAUSTIVE = ("모든", "전국 전체", "전수", "전수조사", "빠짐없이", "유사한 모든", "전체 사례")
_QUESTION_WORDS = {
    "찾아줘","찾아","비교해줘","비교","정리해줘","정리","검토해줘","검토","알려줘","관련","유사한",
    "전국","모든","전체","사례","조례","법령","근거","어떻게","무엇","뭐가","유의점","사항","설치","운영",
}
_ATTRIBUTES = {"본예산", "추경", "추가경정예산", "예산현액", "현액", "집행액", "집행", "지출액", "결산", "예산", "예산안"}
_NOISE = _QUESTION_WORDS | _ATTRIBUTES | {"의회", "지적사항", "질의", "지적", "내용", "최근", "부터", "까지", "연도", "사업", "부서", "및", "관련된", "찾아주세요", "알려주세요", "검토자료", "작성해줘", "만들어줘"}
_STAGE_TERMS = (("original", "본예산"), ("supplementary", "추경"), ("supplementary", "추가경정예산"), ("current", "예산현액"), ("current", "현액"), ("execution", "집행액"), ("settlement", "결산"), ("draft", "예산안"))
_LAW_PATTERNS = [
    re.compile(r"([가-힣A-Za-z0-9·\s]{2,60}?(?:기본법|특별법|법률|법|시행령|시행규칙))(?=\s|제\d+조|에|의|을|를|,|\.|$)")
]
_ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")

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
    for pattern in (r"[\\\"'“”‘’]([^\\\"'“”‘’]{2,60})[\\\"'“”‘’]", r"([가-힣A-Za-z0-9]{2,20}(?:·[가-힣A-Za-z0-9]{2,20})+)"):
        for match in re.findall(pattern,question):
            chunks.extend(re.split(r"·|/|,",match))
    return [x.strip() for x in chunks if x.strip() and x.strip() not in _QUESTION_WORDS]

def _entity_terms(question: str, jurisdiction: str, laws: list[str]) -> list[str]:
    """Keep contiguous subject phrases; attributes and request clauses split them."""
    text = question
    for law in sorted(laws, key=len, reverse=True):
        text = text.replace(law, " | ")
    tokens = re.findall(r"[가-힣A-Za-z0-9]+|[|,·/;]", text)
    chunks, current = [], []
    def flush():
        if current:
            chunks.append(" ".join(current)); current.clear()
    for token in tokens:
        if token in '|,·/;':
            flush(); continue
        # Remove particles only from known request attributes, not policy nouns.
        plain = re.sub(r"(?:부터|까지|으로|에서|을|를|은|는|와|과|에|의)$", "", token)
        if token in _NOISE or plain in _NOISE or re.fullmatch(r"\d+(?:년(?:부터|까지)?|월|일(?:까지)?)?", token) or _ARTICLE.fullmatch(token):
            flush(); continue
        region = resolve_jurisdiction(token)
        if region['state'] in {'resolved', 'ambiguous'} or _norm(token) == _norm(jurisdiction):
            flush(); continue
        if re.search(r"(?:찾아|알려|정리|검토|비교|확인)(?:줘|주세요|해줘|해주세요)$", token):
            flush(); continue
        # A trailing subject/object particle on a named target is safe only for
        # these explicit forms; '문화예술과' remains a department name.
        token = re.sub(r"(?:을|를|에는|에서|의)$", "", token)
        current.append(token)
    flush()
    return _unique(chunks)


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
    subjects=_entity_terms(question,jurisdiction,laws)
    named=[t for t in _quoted_or_named_chunks(question) if t not in _ATTRIBUTES and re.sub(r"(?:과|와|을|를)$", "", t) not in _ATTRIBUTES]
    named=_unique(named)
    core=[t for t in extract_terms(question) if t not in _NOISE and not any(_norm(t)==_norm(x) for x in laws)
          and resolve_jurisdiction(t)['state']=='unresolved']
    generated=[]
    for row in axes:
        generated.extend(row["search_terms"])
    search_terms=_unique(named+subjects+generated+core)[:max_terms]
    exhaustive=any(term in question for term in _EXHAUSTIVE)
    return {
        "question":question.strip(),
        "jurisdiction":jurisdiction.strip(),
        "law_names":laws,
        "article_refs":articles,
        "named_policy_terms":named,
        "target_entities":[{"name":t,"type":"department" if re.search(r"(?:과|국|실|담당관|센터)$",t) else "policy_or_project",
                            "verification":"RULE_BASED_CANDIDATE"} for t in _unique(named+subjects)],
        "budget_stages":_unique([stage for stage, term in _STAGE_TERMS if re.search(r"(?<![가-힣])"+re.escape(term)+r"(?:과|와|을|를)?(?=[^가-힣]|$)",question)]),
        "fiscal_year_mentions":_unique(re.findall(r"(\d{4})년",question)),
        "meeting_period_candidates":re.findall(r"\d{4}년(?:부터|\s*\d{1,2}월(?:\s*\d{1,2}일)?)?",question),
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
    # Complex questions use preserved entity phrases; retain the entire question
    # separately in decompose.question instead of treating it as a search term.
    if plan['target_entities'] and (len(question)>60 or any(t in question for t in ('본예산','추경','의회 지적','집행액'))):
        terms=[t['name'] for t in plan['target_entities']]
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
    ordinance_queries.extend(t["name"] for t in plan["target_entities"])
    for row in plan["functional_axes"]:
        ordinance_queries.extend(row["search_terms"])
    ordinance_queries.extend(plan["core_terms"])
    ordinance_queries=_unique(ordinance_queries)[:max_terms]
    # No explicitly named law: do not send policy or municipality as a law title.
    # Explicit legal citations in retrieved official documents can provide followups.
    return {**plan,"law_queries":law_queries,"ordinance_queries":ordinance_queries}
