"""Hosted session cookie boundary; review mode continues using explicit bearer headers."""
from __future__ import annotations

import hmac
import re
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import hosted


CSRF_HEADER = "x-ft-csrf"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class HostedCookieAuthMiddleware:
    """Adapt a hosted cookie into the existing bearer contract after CSRF validation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not hosted.ENABLED:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        raw_token = request.cookies.get(hosted.SESSION_COOKIE, "")
        if not raw_token or request.headers.get("authorization"):
            await self.app(scope, receive, send)
            return
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", raw_token):
            response = JSONResponse({"detail": "Missing or invalid auth token"}, status_code=401)
            await response(scope, receive, send)
            return
        if request.method.upper() not in SAFE_METHODS:
            supplied = request.headers.get(CSRF_HEADER, "")
            if not hmac.compare_digest(supplied, hosted.csrf_token(raw_token)):
                response = JSONResponse({"detail": "Missing or invalid CSRF token"}, status_code=403)
                await response(scope, receive, send)
                return
        # The token never enters JavaScript or a URL. FastAPI's Header parameter
        # sees the same bearer contract used by review-mode and legacy tests.
        scope["headers"] = [*scope.get("headers", []),
                            (b"authorization", f"Bearer {raw_token}".encode("ascii"))]
        await self.app(scope, receive, send)
