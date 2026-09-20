from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import MutableHeaders


APP_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "connect-src 'self' ws: wss:",
        "font-src 'self' data: https://fonts.gstatic.com",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "frame-src 'none'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "worker-src 'none'",
    )
)

DOCS_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "connect-src 'self'",
        "font-src 'self' data:",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data: https://fastapi.tiangolo.com",
        "object-src 'none'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    )
)

BASE_BROWSER_SECURITY_HEADERS = (
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=(), usb=()"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("X-Permitted-Cross-Domain-Policies", "none"),
)


class BrowserSecurityHeadersMiddleware:
    """Attach browser hardening headers without affecting API response bodies."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_BROWSER_SECURITY_HEADERS:
                    if name not in headers:
                        headers[name] = value
                if path == "/":
                    headers["Content-Security-Policy"] = APP_CONTENT_SECURITY_POLICY
                elif path in {"/docs", "/redoc"}:
                    headers["Content-Security-Policy"] = DOCS_CONTENT_SECURITY_POLICY
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
