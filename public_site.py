"""Public listing, privacy, terms, support and domain-verification pages.

These routes are intentionally tiny and side-effect free. They are served only
when the MCP runs in explicit public-readonly mode. The OpenAI verification
challenge returns the exact configured token as plain text.
"""
from __future__ import annotations

import html
import os
from typing import Optional

DEVELOPER = "전남광주통합특별시 서구청 펀온워크 AI혁신분과 에이블(AIBLE)"
PRODUCT = "지방의회·예산·조례 MCP"


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:860px;margin:48px auto;padding:0 24px;line-height:1.7;color:#17212b}}
h1,h2{{line-height:1.3}} .muted{{color:#667085}} code{{background:#f2f4f7;padding:2px 5px;border-radius:4px}}
a{{color:#175cd3}} footer{{margin-top:48px;padding-top:20px;border-top:1px solid #e4e7ec;color:#667085}}
</style>
</head>
<body>
{body}
<footer>개발·기획: {html.escape(DEVELOPER)}</footer>
</body>
</html>""".encode("utf-8")


ABOUT = _page(PRODUCT, f"""
<h1>{PRODUCT}</h1>
<p>전국 지방의회 공개 회의록·의안 자료를 원문 근거 중심으로 검색하고,
의회 질의·답변, 예산 산출·재원분담 검산, 조례 제정·개정 검토를 한 연결에서 지원합니다. 기존 지방의회MCP의 의회 기능을 포함합니다.</p>
<p><strong>개발·기획:</strong> {DEVELOPER}</p>
<h2>주요 기능</h2>
<ul>
<li>공개 지방의회 회의록·의안 검색</li>
<li>질의·답변 및 발언 근거 확인</li>
<li>CLIK 의원정보를 활용한 관련 공식기록 후보 탐색(Discovery 전용)</li>
<li>국가법령정보 공동활용 연계 시 상위법·자치법규 근거 후보 확인</li>
<li>지방재정365 세부사업별 세출현황 연계 및 재정 컨텍스트</li>
<li>공공데이터포털 검색서비스를 통한 추가 공식 데이터셋 후보 탐색(필요 시)</li>
<li>업무보고·행감·본예산·추경·조례/의안 등 회기 전 원스톱 준비팩</li>
<li>예산 산출·증감·재원분담·다년도 비용 검산</li>
<li>법령·조례 원문 확인, 비교 및 검토용 일부개정문·신구대비 작성</li>
<li>의회·예산·조례를 연결하는 업무 계획과 근거 누락 점검</li>
<li>반복 쟁점·부서별 논의·기간별 검토</li>
<li>공식 원문 링크와 확인 범위 구분</li>
<li>표준 <code>search</code>/<code>fetch</code> 인터페이스</li>
</ul>
<p class="muted">본 서비스는 공개자료 조회용이며 개인정보·비공개 행정자료 입력을 전제로 하지 않습니다.</p>
<p><a href="/privacy">개인정보처리방침</a> · <a href="/terms">이용약관</a> · <a href="/support">지원</a></p>
""")

PRIVACY = _page(f"{PRODUCT} 개인정보처리방침", f"""
<h1>개인정보처리방침</h1>
<p><strong>적용 서비스:</strong> {PRODUCT}</p>
<p><strong>개발·기획:</strong> {DEVELOPER}</p>
<h2>1. 서비스 성격</h2>
<p>{PRODUCT}는 로그인 없이 의회·예산·조례 공개자료를 조회하고 입력한 산출안·검토용 조문을 처리하는 서비스입니다.
서비스 운영자는 사용자 프로필을 만들거나 광고 목적의 행동 프로파일링을 하지 않습니다.</p>
<h2>2. 처리될 수 있는 정보</h2>
<ul>
<li>사용자가 입력한 검색어·지역·기간·예산 산출 조건·검토용 조문 등 질의 파라미터</li>
<li>공개 회의록·재정·법령·조례에서 조회된 근거와 검색 결과</li>
<li>서비스 안정성과 보안을 위한 호스팅 사업자의 일반적인 기술 로그(예: 요청 시각, IP 주소, 요청 경로, 응답 상태)</li>
</ul>
<p>개인정보 또는 비공개 행정자료를 입력하지 않는 것을 원칙으로 합니다.</p>
<h2>3. 이용 목적</h2>
<p>입력된 질의는 공개자료 검색, 예산 검산, 조례 검토 결과를 제공하며,
오류 대응·보안·서비스 안정성 유지에 필요한 범위에서만 처리됩니다.</p>
<h2>4. 보관</h2>
<p>서버는 공개 검색 결과를 성능과 이어보기 기능을 위해 제한된 기간 임시 캐시할 수 있습니다.
현재 검색 캐시는 짧은 시간 단위로 유지되며, 근거 묶음은 기본적으로 최대 약 24시간의 만료 정책을 사용합니다.
Render의 임시 저장소 특성상 재배포나 인스턴스 교체 시 더 일찍 삭제될 수 있습니다.</p>
<h2>5. 외부 서비스</h2>
<p>공개 지방의회 자료 조회는 국회도서관 지방의정포털(CLIK) Open API를 기본 회의록 원천으로 사용합니다. 지방의회 홈페이지 직접 자동수집은 안정성을 위해 사용하지 않습니다.
법령·조례 기능을 사용할 때에는 국가법령정보 공동활용 OPEN API에 요청할 수 있고, 재정 기능 사용 시에는 행정안전부 지방재정365 세부사업별 세출현황 OpenAPI를 사용할 수 있습니다.
사용자가 추가 공식 데이터 탐색을 요청한 경우 공공데이터포털 검색서비스에서 데이터셋/API 후보의 메타데이터를 조회할 수 있으며, 검색된 외부 API를 자동 실행하지 않습니다.
예산 카탈로그에서 선택한 공식 API는 지방재정365·공공데이터포털·KOSIS 등에 요청합니다. 서버의 별도 생성형 AI 호출은 사용하지 않습니다. 예산·조례 검토 입력은 결과 반환을 위한 일시 처리에 사용하며 공개 검색 보관함에 저장하지 않습니다.
호스팅은 Render를 사용합니다. 각 제공자의 기술 로그와 보관은 해당 제공자의 정책에 따를 수 있습니다.</p>
<h2>6. 판매·광고</h2>
<p>사용자 데이터를 판매하지 않으며 맞춤형 광고 목적으로 사용하지 않습니다.</p>
<h2>7. 문의</h2>
<p>지원 연락처는 <a href="/support">지원 페이지</a>에서 확인할 수 있습니다.</p>
<p class="muted">최종 갱신: 2026-09-30</p>
""")

TERMS = _page(f"{PRODUCT} 이용약관", f"""
<h1>이용약관</h1>
<p><strong>적용 서비스:</strong> {PRODUCT}</p>
<p><strong>개발·기획:</strong> {DEVELOPER}</p>
<h2>1. 목적</h2>
<p>본 서비스는 공개 지방의회 자료의 검색과 근거 확인을 지원합니다.</p>
<h2>2. 정보의 성격</h2>
<p>결과는 공개 원문과 자동 파싱·검색을 바탕으로 제공됩니다. 검색 누락, 원문 형식 변화,
상류 서비스 장애 또는 파싱 오차가 있을 수 있으며 최종 행정·법률 판단은 공식 원문과 담당기관 확인을 우선해야 합니다.</p>
<h2>3. 이용자 책임</h2>
<ul>
<li>개인정보, 비공개 행정자료, 비밀정보를 검색어로 입력하지 않습니다.</li>
<li>제3자의 권리와 관련 법령을 침해하는 방식으로 서비스를 사용하지 않습니다.</li>
<li>자동화된 대량 호출 등 서비스 안정성을 해치는 사용을 하지 않습니다.</li>
</ul>
<h2>4. 서비스 변경 및 중단</h2>
<p>공개 API, 지방의회 홈페이지, 호스팅 환경 또는 제품 정책 변경에 따라 일부 기능이 변경·지연·중단될 수 있습니다.</p>
<h2>5. 출처</h2>
<p>가능한 경우 원문 링크를 함께 제공하며, 원문 확인 상태와 미확인 범위를 구분합니다.</p>
<p class="muted">최종 갱신: 2026-09-30</p>
""")

def _support_page() -> bytes:
    email = os.environ.get("UIJEONG_SUPPORT_EMAIL", "").strip()
    if email:
        contact = f'<a href="mailto:{html.escape(email, quote=True)}">{html.escape(email)}</a>'
    else:
        contact = "공개 제출 전 운영자가 지원 이메일 또는 공개 문의 채널을 설정합니다."
    return _page(f"{PRODUCT} 지원", f"""
<h1>지원</h1>
<p><strong>서비스:</strong> {PRODUCT}</p>
<p><strong>개발·기획:</strong> {DEVELOPER}</p>
<p><strong>문의:</strong> {contact}</p>
<h2>문의 시 포함하면 좋은 정보</h2>
<ul>
<li>질문에 사용한 의회명과 검색어</li>
<li>오류 발생 시각과 화면에 표시된 오류 메시지</li>
<li>COMPLETE / PARTIAL / EMPTY / ERROR 중 표시된 상태</li>
</ul>
<p>API 키, 인증토큰, 개인정보·비공개 행정자료는 문의 내용에 포함하지 마세요.</p>
""")


def route(path: str, method: str) -> Optional[tuple[int, bytes, bytes]]:
    """Return (status, content_type, body) for public info routes."""
    if method not in ("GET", "HEAD"):
        return None
    clean = (path or "/").rstrip("/") or "/"

    if clean == "/.well-known/openai-apps-challenge":
        token = os.environ.get("OPENAI_APPS_CHALLENGE", "").strip()
        if not token:
            return 404, b"text/plain; charset=utf-8", b"Not configured"
        # OpenAI requires the exact token only: no JSON, no list, no newline.
        return 200, b"text/plain; charset=utf-8", token.encode("utf-8")

    pages = {
        "/": ABOUT,
        "/about": ABOUT,
        "/privacy": PRIVACY,
        "/terms": TERMS,
        "/support": _support_page(),
    }
    body = pages.get(clean)
    if body is None:
        return None
    return 200, b"text/html; charset=utf-8", body
