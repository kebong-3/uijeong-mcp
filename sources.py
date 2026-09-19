"""Verified source registry and pure discovery helpers (no network or secret access).

Directory entries are discovery data, not a claim that an automatic adapter exists.
Only the main module's registered adapters may fetch remote pages.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

DATA_DIR = Path(__file__).resolve().parent / "data"
MAX_HTML_CHARS = 2_000_000


def _load(filename: str) -> dict:
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


def council_code_map(include_historical: bool = True) -> dict[str, str]:
    return {c["council_id"]: c["name"] for c in _load("council_codes.json")["councils"]
            if include_historical or c["status"] == "current_code_table"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text))).removesuffix("의회")


def _query_variants(query: str) -> set[str]:
    q = query.strip()
    variants = {_norm(q)}
    prefixes = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
                "인천": "인천광역시", "대전": "대전광역시", "울산": "울산광역시",
                "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도",
                "충남": "충청남도", "전북": "전북특별자치도", "경북": "경상북도",
                "경남": "경상남도", "제주": "제주특별자치도", "세종": "세종특별자치시"}
    for short, long in prefixes.items():
        if q == short or q.startswith(short + " "):
            variants.add(_norm(long + q[len(short):]))
    return variants


def resolve_councils(query: str) -> list[dict]:
    """Exact names/aliases first, then candidates. Never silently select ambiguity."""
    q = (query or "").strip()
    if not q:
        return []
    rows = _load("council_codes.json")["councils"]
    if re.fullmatch(r"\d{6}", q):
        return [copy.deepcopy(r) for r in rows if r["council_id"] == q]
    variants = _query_variants(q)
    if _norm(q) == "광주시":
        return [copy.deepcopy(r) for r in rows if r["council_id"] == "031006"]
    def names(r):
        return {_norm(n) for n in [r["name"], *r.get("aliases", [])]}
    exact = [r for r in rows if variants & names(r)]
    hits = exact or [r for r in rows if any(v in n for v in variants for n in names(r))]
    return copy.deepcopy(hits)


def load_sources() -> dict:
    return _load("council_sources.json")


def search_sources(query: str = "", region: str = "", direct_only: bool = False,
                   offset: int = 0, limit: int = 20) -> dict:
    """List source coverage, paginated without conflating directory and adapters."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset은 0 이상의 정수여야 합니다.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit은 1~100 사이의 정수여야 합니다.")
    registry = load_sources()
    rows = registry["sources"]
    if query:
        candidates = resolve_councils(query)
        ids = {r["council_id"] for r in candidates}
        qs = _query_variants(query)
        rows = ([r for r in rows if r.get("council_id") in ids] if ids else
                [r for r in rows if any(q in _norm(n) for q in qs for n in
                 [r["name"], r.get("directory_name") or "", r.get("official_host") or "", *r.get("aliases", [])])])
    if region:
        regions = _query_variants(region)
        rows = [r for r in rows if any(q in _norm(r["region"]) or
                    q in _norm(r.get("directory_name") or "") for q in regions)]
    if direct_only:
        rows = [r for r in rows if r.get("direct_adapter")]
    total = len(rows)
    return {"status": "COMPLETE" if total else "EMPTY", "checked_at": registry["checked_at"],
            "registry_scope": registry["registry_scope"], "official_directory_url": registry["official_directory_url"],
            "registry_total": registry["source_count"], "directory_host_count": registry["directory_host_count"],
            "current_code_count": 243, "historical_code_count": 2,
            "direct_adapter_count": sum(bool(r.get("direct_adapter")) for r in registry["sources"]),
            "total_matches": total, "offset": offset, "returned": len(rows[offset:offset + limit]),
            "next_offset": offset + limit if offset + limit < total else None,
            "sources": copy.deepcopy(rows[offset:offset + limit]),
            "limits": ["등록된 의회 수와 CLIK에 자료가 수록된 의회 수는 다릅니다.",
                       "홈페이지 관측은 MCP 자동수집·회의록 원문 추출 성공을 뜻하지 않습니다.",
                       "공식 디렉터리에 남은 구 명칭·구 주소는 신설 의회로 자동 연결하지 않습니다."]}


def official_hosts() -> set[str]:
    return {r["official_host"] for r in load_sources()["sources"] if r.get("official_host")}


def validate_official_source_url(url: str) -> str:
    """Validate a reference URL only; does not authorize fetching arbitrary paths."""
    if not isinstance(url, str) or not url or len(url) > 4096 or re.search(r"[\x00-\x20\\]", url):
        raise ValueError("원문 주소 형식이 올바르지 않습니다.")
    try:
        p = urlsplit(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            raise ValueError
        if p.hostname not in official_hosts() | {"clik.nanet.go.kr"}:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("확인된 공식 호스트의 HTTPS 주소만 원문 참조로 사용할 수 있습니다.") from None
    secret_params = {"apikey", "api_key", "servicekey", "access_token", "authorization", "password", "secret"}
    if any(k.lower() in secret_params or (p.hostname == "clik.nanet.go.kr" and k.lower() == "key")
           for k, _ in parse_qsl(p.query, keep_blank_values=True)):
        raise ValueError("인증정보가 포함된 주소는 원문 참조로 저장할 수 없습니다.")
    return url


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.href = None
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignored += 1
        if tag == "a" and not self.ignored:
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignored = max(0, self.ignored - 1)
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(self.parts).strip()))
            self.href, self.parts = None, []

    def handle_data(self, data):
        if self.href is not None and not self.ignored:
            self.parts.append(data)


def discover_minutes_links(html: str, base_url: str, limit: int = 30) -> dict:
    """Extract candidate links from supplied HTML. No crawl; no source upgrade.

    Different hosts and script URLs are excluded, even when another host is in
    the registry. Each newly registered adapter still needs robots/parser QA.
    """
    validate_official_source_url(base_url)
    if not isinstance(html, str) or len(html) > MAX_HTML_CHARS:
        raise ValueError("HTML은 2,000,000자 이하의 문자열이어야 합니다.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit은 1~100 사이의 정수여야 합니다.")
    parser = _LinkParser()
    parser.feed(html)
    host = urlsplit(base_url).hostname
    links, seen = [], set()
    for href, label in parser.links:
        if not re.search(r"회의록|5\s*분|자유발언|구정질문|시정질문|행정사무감사|의안", label):
            continue
        candidate = urljoin(base_url, href)
        try:
            validate_official_source_url(candidate)
        except ValueError:
            continue
        if urlsplit(candidate).hostname != host or candidate in seen or href.startswith("#"):
            continue
        seen.add(candidate)
        links.append({"label": label[:200], "url": candidate,
                      "verification": "candidate_from_user_provided_html", "fetched": False})
    return {"status": "COMPLETE" if links else "EMPTY", "source_kind": "USER_PROVIDED",
            "base_url": base_url, "total_candidates": len(links), "links": links[:limit],
            "truncated": len(links) > limit,
            "limits": ["링크 후보 추출만 수행; 공개 회의록 여부·현재 접속·robots 허용·원문 파싱 미검증."]}
