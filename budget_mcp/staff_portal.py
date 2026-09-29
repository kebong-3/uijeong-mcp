"""Static employee onboarding; fixed logo asset, no uploads or network proxy."""
from __future__ import annotations
import base64
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).with_name('staff')


def page_csp(text: str) -> str:
    """Permit only checked-in interaction scripts and same-origin images."""
    scripts = re.findall(r'<script>([\s\S]*?)</script>', text)
    hashes = ["'sha256-" + base64.b64encode(hashlib.sha256(s.encode('utf-8')).digest()).decode('ascii') + "'" for s in scripts]
    return "default-src 'none'; style-src 'unsafe-inline'; script-src " + (' '.join(hashes) or "'none'") + "; connect-src 'none'; img-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'"


def staff_routes():
    from starlette.responses import HTMLResponse, PlainTextResponse, Response
    from starlette.routing import Route
    # Fixed checked-in paths only. No query or request path selects a file.
    contents = {name: (ROOT / name).read_text('utf-8') for name in ('index.html', 'board.html', 'prompts.txt', 'announcement.txt')}
    logo_bytes = (ROOT / 'logo.webp').read_bytes()
    common = {'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'}

    async def staff(request):
        return HTMLResponse(contents['index.html'], headers={**common, 'Content-Security-Policy': page_csp(contents['index.html'])})

    async def board(request):
        return HTMLResponse(contents['board.html'], headers={**common, 'Content-Security-Policy': page_csp(contents['board.html'])})

    async def prompts(request):
        return PlainTextResponse(contents['prompts.txt'], headers=common)

    async def announcement(request):
        return PlainTextResponse(contents['announcement.txt'], headers=common)

    async def logo(request):
        return Response(logo_bytes, media_type='image/webp', headers=common)

    return [Route('/staff', staff), Route('/staff/', staff), Route('/staff/board.html', board),
            Route('/staff/prompts.txt', prompts), Route('/staff/announcement.txt', announcement),
            Route('/staff/logo.webp', logo)]

