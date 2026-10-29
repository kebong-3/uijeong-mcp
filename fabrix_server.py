#!/usr/bin/env python3
"""FabriX repository entry point: python fabrix_server.py (HTTP, default 8080).

Runs the local public tool implementation; no Render proxy or API-key download.
Set UIJEONG_ALLOWED_HOSTS or FABRIX_SERVER_URL for the actual gateway Host.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from urllib.parse import urlsplit


def configure_environment() -> None:
    # These defaults apply only to this explicit public, read-only launcher.
    defaults = {
        "PORT": "8080",
        "UIJEONG_AUTH_MODE": "public",
        "UIJEONG_PUBLIC_READONLY": "true",
        "UIJEONG_BIND_HOST": "0.0.0.0",
        "UIJEONG_PROFILE": "core",
        "UIJEONG_CACHE_MAX_ENTRIES": "200",
        "UIJEONG_SNAPSHOT_MAX_ENTRIES": "200",
        "UIJEONG_SNAPSHOT_MAX_TOTAL_BYTES": "67108864",
        "UIJEONG_STATE_DB": str(Path(tempfile.gettempdir()) / "uijeong-fabrix" / "state.sqlite3"),
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    try:
        port = int(os.environ["PORT"])
    except ValueError:
        raise ValueError("PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer from 1 to 65535.")
    if os.environ["UIJEONG_AUTH_MODE"].strip().lower() not in ("public", "none"):
        raise ValueError("fabrix_server.py requires UIJEONG_AUTH_MODE=public (user authentication: unused).")
    if os.environ["UIJEONG_PUBLIC_READONLY"].lower() != "true":
        raise ValueError("fabrix_server.py requires UIJEONG_PUBLIC_READONLY=true.")

    if "UIJEONG_ALLOWED_HOSTS" not in os.environ:
        # Permit local/container probes without accepting arbitrary external Hosts.
        names = ["127.0.0.1", "localhost", "[::1]", socket.gethostname().lower()]
        hosts = [entry for name in names for entry in (name, f"{name}:{port}")]
        url = os.environ.get("FABRIX_SERVER_URL", "").strip()
        if url:
            try:
                parts = urlsplit(url)
                valid = (parts.scheme in ("http", "https") and parts.hostname
                         and not parts.username and not parts.password and parts.port != 0
                         and not any(c in parts.netloc for c in "*\\")
                         and not any(c.isspace() for c in url))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("FABRIX_SERVER_URL must be an HTTP(S) server URL without credentials or wildcards.")
            hosts.append(parts.netloc.lower())
        os.environ["UIJEONG_ALLOWED_HOSTS"] = ",".join(dict.fromkeys(hosts))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check local HTTP/tool contracts without upstream API calls")
    args = parser.parse_args()
    try:
        configure_environment()
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import runtime_security as security
        policy = security.http_policy()
        from public_server import run, self_test
        if args.check:
            result = asyncio.run(self_test())
            print(json.dumps({"launcher": "fabrix", "port": policy["port"],
                              "mcp_path": "/mcp", "public_protocol": result}, ensure_ascii=False))
        else:
            run()
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
