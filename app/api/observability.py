from __future__ import annotations

import json
import logging
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from traceback import extract_tb
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_LOGGER = logging.getLogger("family_tree.request")
REQUEST_LOGGER.setLevel(logging.INFO)
if not any(getattr(handler, "_family_tree_request_handler", False) for handler in REQUEST_LOGGER.handlers):
    request_log_handler = logging.StreamHandler(sys.stderr)
    request_log_handler.setFormatter(logging.Formatter("%(message)s"))
    request_log_handler._family_tree_request_handler = True  # type: ignore[attr-defined]
    REQUEST_LOGGER.addHandler(request_log_handler)

LATENCY_BUCKETS_MS = (10.0, 25.0, 50.0, 100.0, 250.0, 400.0, 1000.0, 2500.0, 5000.0)
READ_P95_TARGET_MS = 250.0
WRITE_P95_TARGET_MS = 400.0
MINIMUM_BUDGET_SAMPLES = 20
STANDARD_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})


@dataclass
class RouteMetric:
    request_count: int = 0
    client_error_count: int = 0
    server_error_count: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    latency_bucket_counts: list[int] = field(
        default_factory=lambda: [0] * (len(LATENCY_BUCKETS_MS) + 1)
    )


class RequestMetrics:
    """Bounded, process-local route metrics with no raw paths or request data."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._routes: dict[tuple[str, str], RouteMetric] = {}

    def reset(self) -> None:
        with self._lock:
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._routes.clear()

    def record(self, method: str, route: str, status_code: int, duration_ms: float) -> None:
        safe_method = method if method in STANDARD_HTTP_METHODS else "OTHER"
        safe_route = route if route.startswith("/") else "<unmatched>"
        with self._lock:
            metric = self._routes.setdefault((safe_method, safe_route), RouteMetric())
            metric.request_count += 1
            if 400 <= status_code < 500:
                metric.client_error_count += 1
            elif status_code >= 500:
                metric.server_error_count += 1
            metric.total_duration_ms += duration_ms
            metric.max_duration_ms = max(metric.max_duration_ms, duration_ms)
            bucket_index = next(
                (index for index, upper_bound in enumerate(LATENCY_BUCKETS_MS) if duration_ms <= upper_bound),
                len(LATENCY_BUCKETS_MS),
            )
            metric.latency_bucket_counts[bucket_index] += 1

    @staticmethod
    def _quantile_upper_bound(metric: RouteMetric, quantile: float) -> float | None:
        if not metric.request_count:
            return None
        threshold = max(1, int(metric.request_count * quantile + 0.999999))
        seen = 0
        for index, count in enumerate(metric.latency_bucket_counts):
            seen += count
            if seen >= threshold:
                return LATENCY_BUCKETS_MS[index] if index < len(LATENCY_BUCKETS_MS) else None
        return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            started_at = self._started_at
            route_items = [
                (method, route, RouteMetric(**{
                    "request_count": metric.request_count,
                    "client_error_count": metric.client_error_count,
                    "server_error_count": metric.server_error_count,
                    "total_duration_ms": metric.total_duration_ms,
                    "max_duration_ms": metric.max_duration_ms,
                    "latency_bucket_counts": metric.latency_bucket_counts.copy(),
                }))
                for (method, route), metric in self._routes.items()
            ]

        routes = []
        for method, route, metric in sorted(route_items, key=lambda item: (item[0], item[1])):
            target_ms = READ_P95_TARGET_MS if method in {"GET", "HEAD"} else WRITE_P95_TARGET_MS
            p95_upper_bound_ms = self._quantile_upper_bound(metric, 0.95)
            if metric.request_count < MINIMUM_BUDGET_SAMPLES:
                budget_status = "insufficient_samples"
            elif p95_upper_bound_ms is None or p95_upper_bound_ms > target_ms:
                budget_status = "exceeded"
            else:
                budget_status = "within"
            routes.append({
                "method": method,
                "route": route,
                "request_count": metric.request_count,
                "client_error_count": metric.client_error_count,
                "server_error_count": metric.server_error_count,
                "mean_duration_ms": round(metric.total_duration_ms / metric.request_count, 2),
                "max_duration_ms": round(metric.max_duration_ms, 2),
                "p50_upper_bound_ms": self._quantile_upper_bound(metric, 0.50),
                "p95_upper_bound_ms": p95_upper_bound_ms,
                "p95_target_ms": target_ms,
                "budget_status": budget_status,
                "latency_bucket_counts": metric.latency_bucket_counts,
            })
        return {
            "scope": "process",
            "started_at": started_at,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "minimum_budget_samples": MINIMUM_BUDGET_SAMPLES,
            "latency_bucket_upper_bounds_ms": [*LATENCY_BUCKETS_MS, None],
            "routes": routes,
        }


REQUEST_METRICS = RequestMetrics()


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "<unmatched>"


def _request_event(
    request: Request,
    *,
    request_id: str,
    status_code: int,
    duration_ms: float,
    outcome: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "duration_ms": round(duration_ms, 2),
        "event": "http_request",
        "method": request.method,
        "outcome": outcome,
        "request_id": request_id,
        "route": _route_template(request),
        "status_code": status_code,
    }
    if error_type:
        event["error_type"] = error_type
    return event


class RequestObservabilityMiddleware:
    """Correlate and time HTTP requests without logging bodies, queries, or credentials."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = perf_counter()
        status_code = 500
        response_started = False

        async def send_with_observability(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                duration_ms = (perf_counter() - started_at) * 1000
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
                response_headers["Server-Timing"] = f"app;dur={duration_ms:.2f}"
            await send(message)

        try:
            await self.app(scope, receive, send_with_observability)
        except Exception as exc:
            duration_ms = (perf_counter() - started_at) * 1000
            event = _request_event(
                request,
                request_id=request_id,
                status_code=500,
                duration_ms=duration_ms,
                outcome="server_error",
                error_type=type(exc).__name__,
            )
            event["stack"] = [
                {"function": frame.name, "line": frame.lineno}
                for frame in extract_tb(exc.__traceback__)[-8:]
            ]
            REQUEST_METRICS.record(request.method, _route_template(request), 500, duration_ms)
            REQUEST_LOGGER.error(json.dumps(event, separators=(",", ":"), sort_keys=True))
            if response_started:
                raise
            response = JSONResponse(
                status_code=500,
                content={"detail": "Unexpected server error", "request_id": request_id},
                headers={
                    REQUEST_ID_HEADER: request_id,
                    "Server-Timing": f"app;dur={duration_ms:.2f}",
                },
            )
            await response(scope, receive, send)
            return

        duration_ms = (perf_counter() - started_at) * 1000
        event = _request_event(
            request,
            request_id=request_id,
            status_code=status_code,
            duration_ms=duration_ms,
            outcome=(
                "success"
                if status_code < 400
                else ("client_error" if status_code < 500 else "server_error")
            ),
        )
        REQUEST_METRICS.record(request.method, event["route"], status_code, duration_ms)
        log_method = REQUEST_LOGGER.info if status_code < 500 else REQUEST_LOGGER.error
        log_method(json.dumps(event, separators=(",", ":"), sort_keys=True))
