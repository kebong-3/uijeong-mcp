"""공개 MCP 도구를 평범한 HTTP JSON으로 부르는 얇은 다리(REST bridge).

웹 앱은 MCP 접속 절차(initialize → tools/call)를 흉내 낼 필요가 없다. 이 다리는
새 기능을 만들지 않는다. 공개 서버에 이미 등록된 도구를 같은 FastMCP 서버의
call_tool로 그대로 부르므로 다음이 MCP 경로와 똑같이 적용된다.

- 허용목록: public_server.PUBLIC_TOOLS 밖의 이름은 404. 내부 보관함·초안 도구는 부를 수 없다.
- 입력 검증: 도구 스키마(pydantic)와 공개 상한(max_docs 등)을 그대로 통과해야 한다.
- 혼잡 제어: 바깥 HTTPGuard·PublicBoundary의 Host/Origin 검사, 본문 크기, 분당 한도,
  동시 조회 슬롯을 거친 뒤에만 여기 도달한다. 도구 단위 동시 실행 3개 제한도 그대로다.
- 응답 크기: 도구 결과는 wire_result의 응답 예산을 거친 구조화 결과를 그대로 싣는다.

켜는 방법: UIJEONG_REST_ENABLED=true. 끄면 /api/v1 경로는 이전처럼 404다.
선택 잠금: UIJEONG_REST_KEY(24자 이상)를 두면 X-Uijeong-Key 헤더가 일치해야 한다.
브라우저 직접 호출(CORS)은 열지 않는다. 웹 앱의 서버 함수(예: Vercel /api)에서 부른다.
"""
from __future__ import annotations

import hmac
import json
import os
from typing import Any

import runtime_security as R

PREFIX = "/api/v1"
MAX_MESSAGE_CHARS = 500
KEY_HEADER = b"x-uijeong-key"


def enabled() -> bool:
    return os.environ.get("UIJEONG_REST_ENABLED", "").strip().lower() == "true"


def rest_key() -> str:
    key = os.environ.get("UIJEONG_REST_KEY", "").strip()
    if key and len(key) < 24:
        raise R.SecurityError("UIJEONG_REST_KEY는 24자 이상의 무작위 값이어야 합니다.")
    return key


def is_rest_path(path: str) -> bool:
    path = (path or "").rstrip("/")
    return path == PREFIX or path.startswith(PREFIX + "/")


def _headers() -> list[tuple[bytes, bytes]]:
    return [(b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff")]


async def _reply(send: Any, status: int, payload: dict[str, Any], *, head: bool = False,
                 extra: list[tuple[bytes, bytes]] | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status, "headers": _headers() + (extra or [])})
    await send({"type": "http.response.body", "body": b"" if head else body})


def _short(message: Any) -> str:
    text = R.redact_secrets(str(message or ""))
    return text if len(text) <= MAX_MESSAGE_CHARS else text[:MAX_MESSAGE_CHARS] + "…"


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _text_of(blocks: Any) -> str:
    out = []
    for block in blocks or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if isinstance(text, str):
            out.append(text)
    return "\n".join(out)


def normalize(raw: Any) -> tuple[bool, dict[str, Any] | None, str]:
    """FastMCP call_tool의 세 가지 반환 형태를 (is_error, structured, text)로 맞춘다."""
    if isinstance(raw, tuple) and len(raw) == 2:
        blocks, structured = raw
        return False, structured if isinstance(structured, dict) else None, _text_of(blocks)
    structured = getattr(raw, "structuredContent", None)
    text = _text_of(getattr(raw, "content", None))
    if not isinstance(structured, dict) and text:
        try:
            parsed = json.loads(text)
            structured = parsed if isinstance(parsed, dict) else None
        except ValueError:
            structured = None
    return bool(getattr(raw, "isError", False)), structured if isinstance(structured, dict) else None, text


class RestBridge:
    """/api/v1 경로만 가로채고 나머지(/mcp)는 원래 MCP 앱으로 넘긴다."""

    def __init__(self, app: Any, server: Any, allowed: tuple[str, ...] | list[str]) -> None:
        self.app, self.server, self.allowed = app, server, tuple(allowed)
        self.key = rest_key()
        # HTTPGuard는 공개 모드에서 이 표시가 있는 앱만 받는다. 감싼 앱도 같은 성격이다.
        self.uijeong_public_readonly = bool(getattr(app, "uijeong_public_readonly", False))
        self._tools: list[dict[str, Any]] | None = None

    @property
    def router(self) -> Any:  # 시험·수명주기 코드가 raw.router.lifespan_context를 쓴다.
        return self.app.router

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not enabled() or not is_rest_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        head = method == "HEAD"
        if self.key:
            supplied = dict(scope.get("headers") or []).get(KEY_HEADER, b"")
            if not hmac.compare_digest(supplied, self.key.encode()):
                await _reply(send, 401, {"ok": False, "code": "REST_KEY_REQUIRED",
                                         "message": "X-Uijeong-Key 헤더가 필요합니다."}, head=head)
                return
        path = scope.get("path", "").rstrip("/")
        if path == PREFIX:
            if method not in ("GET", "HEAD"):
                await _reply(send, 405, {"ok": False, "code": "METHOD_NOT_ALLOWED"}, head=head,
                             extra=[(b"allow", b"GET, HEAD")])
                return
            await _reply(send, 200, self._index(), head=head)
            return
        if path == PREFIX + "/tools":
            if method not in ("GET", "HEAD"):
                await _reply(send, 405, {"ok": False, "code": "METHOD_NOT_ALLOWED"}, head=head,
                             extra=[(b"allow", b"GET, HEAD")])
                return
            await _reply(send, 200, {"ok": True, "tools": await self._listing()}, head=head)
            return
        if path.startswith(PREFIX + "/tools/"):
            name = path[len(PREFIX + "/tools/"):]
            if "/" in name or name not in self.allowed:
                await _reply(send, 404, {"ok": False, "code": "UNKNOWN_TOOL",
                                         "message": "공개 허용목록에 없는 도구입니다. GET /api/v1/tools로 확인하세요."},
                             head=head)
                return
            if method != "POST":
                await _reply(send, 405, {"ok": False, "code": "METHOD_NOT_ALLOWED",
                                         "message": "도구 호출은 POST이며 본문은 인자 JSON 객체입니다."},
                             head=head, extra=[(b"allow", b"POST")])
                return
            await self._call(name, receive, send)
            return
        await _reply(send, 404, {"ok": False, "code": "NOT_FOUND"}, head=head)

    def _index(self) -> dict[str, Any]:
        from release_info import VERSION
        return {"ok": True, "service": "지방의회·예산·조례 MCP REST", "version": VERSION,
                "tools": PREFIX + "/tools", "call": "POST " + PREFIX + "/tools/{name}",
                "body": "도구 인자 JSON 객체", "key_required": bool(self.key),
                "browser_cors": False,
                "note": "MCP와 같은 공개 허용목록·입력 상한·혼잡 제어를 거칩니다. 웹 앱의 서버 함수에서 호출하세요."}

    async def _listing(self) -> list[dict[str, Any]]:
        if self._tools is None:
            rows = []
            for tool in await self.server.list_tools():
                if tool.name in self.allowed:
                    rows.append({"name": tool.name, "summary": _first_line(tool.description),
                                 "input_schema": tool.inputSchema})
            self._tools = sorted(rows, key=lambda row: row["name"])
        return self._tools

    async def _call(self, name: str, receive: Any, send: Any) -> None:
        chunks = []
        while True:
            event = await receive()
            if event.get("type") == "http.disconnect":
                return
            chunks.append(event.get("body", b""))
            if not event.get("more_body", False):
                break
        raw_body = b"".join(chunks).strip()
        try:
            arguments = json.loads(raw_body) if raw_body else {}
        except (ValueError, UnicodeError):
            await _reply(send, 400, {"ok": False, "code": "INVALID_JSON",
                                     "message": "본문은 도구 인자를 담은 JSON 객체여야 합니다."})
            return
        if not isinstance(arguments, dict):
            await _reply(send, 400, {"ok": False, "code": "INVALID_JSON",
                                     "message": "본문은 JSON 객체여야 합니다(배열·문자열 불가)."})
            return
        try:
            raw = await self.server.call_tool(name, arguments)
        except Exception as exc:  # FastMCP ToolError: 스키마 위반 또는 표준 search/fetch 실패
            message = _short(exc)
            if "validation error" in message:
                await _reply(send, 422, {"ok": False, "tool": name, "code": "INVALID_ARGUMENTS",
                                         "message": message})
                return
            await _reply(send, 200, {"ok": False, "tool": name, "status": "ERROR",
                                     "code": "TOOL_FAILED", "message": message, "result": None})
            return
        is_error, structured, text = normalize(raw)
        status = (structured or {}).get("status") if isinstance((structured or {}).get("status"), str) else None
        ok = not is_error and status not in ("ERROR", "INVALID_INPUT")
        payload: dict[str, Any] = {"ok": ok, "tool": name, "status": status or ("ERROR" if is_error else "COMPLETE"),
                                   "result": structured}
        if structured is None:
            payload["text"] = text
        await _reply(send, 200, payload)
