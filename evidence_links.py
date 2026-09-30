"""Clickable references preserve document, dataset, catalog and search scopes."""
from __future__ import annotations
import re
from urllib.parse import parse_qsl, urlsplit

URL_KEYS = ("source_url", "citation_url", "body_url", "dataset_url", "detail_url", "ORGINL_FILE_URL", "source_ref")
MAX_LINKS = 16
MAX_NODES = 1200

def safe_reference(value):
    if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\x00-\x20<>]", value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        keys = {k.lower() for k, _ in parse_qsl(p.query)}
        if keys & {"oc", "servicekey", "apikey", "api_key", "access_token", "token", "authorization"}:
            return None
        if "key" in keys and not (p.hostname in {"www.gjsc.or.kr", "gjsc.or.kr"}
                and p.path in {"/record/recordView.do", "/record/originalDownload.do", "/record/appendixDownload.do"}):
            return None
        if "/lf/hub/" in p.path or "/DRF/" in p.path or p.path.endswith("/openapi/minutes.do"):
            return None
        return value
    except (ValueError, TypeError):
        return None

def markdown(label, url):
    label = re.sub(r"[\[\]<>\r\n]", "", str(label or "출처 확인"))[:160]
    return f"[{label}]({url.replace('(', '%28').replace(')', '%29')})"

def attach_source_links(payload, tool=""):
    if not isinstance(payload, dict):
        return payload
    links, seen = [], set()
    count, unlinked, omitted = 0, False, False
    def add(value, label, kind, status="REFERENCE_PROVIDED", details=None):
        nonlocal omitted
        url = safe_reference(value)
        if not url:
            return
        if url in seen:
            if details:
                existing = next(entry for entry in links if entry["url"] == url)
                if "lookup" not in existing:
                    existing["lookup"] = details
            return
        if len(links) >= MAX_LINKS:
            omitted = True
            return
        seen.add(url)
        entry = {"url": url, "label": str(label or "출처 확인")[:160], "markdown": markdown(label, url),
                 "kind": kind, "status": status, "direct_document": kind == "DOCUMENT_REFERENCE"}
        if details:
            entry["lookup"] = details
        links.append(entry)
    def walk(node, depth=0):
        nonlocal count, unlinked, omitted
        if depth > 12 or count >= MAX_NODES:
            omitted = True
            return
        count += 1
        if isinstance(node, dict):
            meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            title = node.get("title") or node.get("project_name") or node.get("name") or meta.get("meeting_name") or meta.get("title")
            link = node.get("source_link")
            if isinstance(link, dict):
                kind = "OFFICIAL_DATASET" if link.get("kind") == "OFFICIAL_DATASET" else "DOCUMENT_REFERENCE"
                add(link.get("url"), link.get("label") or title or "원문 확인", kind,
                    link.get("status") or "REFERENCE_PROVIDED", link.get("lookup"))
            for key in URL_KEYS:
                value = node.get(key)
                if not safe_reference(value):
                    continue
                p = urlsplit(value)
                if key == "dataset_url":
                    kind, label = "OFFICIAL_DATASET", "공식 데이터셋 확인"
                elif p.hostname == "www.data.go.kr" or key == "detail_url":
                    kind, label = "CATALOG_METADATA", title or "공식 자료 설명·제공범위"
                else:
                    kind, label = "DOCUMENT_REFERENCE", title or "공식 원문 확인"
                add(value, label, kind, node.get("source_url_status") or node.get("citation_status") or "REFERENCE_PROVIDED")
            if node.get("docid") and str(node.get("source", "")).upper() == "CLIK":
                prov = node.get("provenance", {})
                unlinked |= not any(safe_reference(node.get(k)) or (isinstance(prov, dict) and safe_reference(prov.get(k))) for k in URL_KEYS)
            for key, value in node.items():
                if key not in {"source_links", "source_link", "link_guidance", "answer_guidance"}:
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)
    walk(payload)
    if unlinked and not any("clik.nanet.go.kr" in link["url"] for link in links):
        add("https://clik.nanet.go.kr/", "CLIK 공식 검색(개별 원문 링크 미확인)", "OFFICIAL_SEARCH", "SEARCH_REFERENCE")
    if links:
        payload["source_links"] = links
        payload["link_guidance"] = {
            "display": "각 핵심 사실·수치 뒤에 해당 source_links.markdown을 붙이고 자료별로 연결하세요.",
            "scope": "DOCUMENT_REFERENCE=원문 주소, OFFICIAL_DATASET=데이터셋 안내, CATALOG_METADATA=자료 설명, OFFICIAL_SEARCH=검색 화면.",
            "verification": "링크 제공과 페이지 본문 조회·대조는 다릅니다. status와 열람 범위를 유지하세요.",
            "links_omitted": omitted}
    return payload
