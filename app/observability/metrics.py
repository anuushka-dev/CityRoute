# app/observability/metrics.py

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from app.observability.reliability_metrics import (
    ReliabilityMetrics,
    get_reliability_metrics,
)

def _route_template(request: Request) -> str:
    """Return a normalized request path for metrics labeling."""

    route = request.scope.get("route")

    path_format = (
        getattr(route, "path_format", None)
        or getattr(route, "path", None)
    )

    if path_format:
        return str(path_format)

    path = request.url.path or "/"

    return path.split(
        "?",
        maxsplit=1,
    )[0]

def _http_outcome_for_status(
    status_code: int,
) -> str:
    if status_code == 504:
        return "timeout"

    if status_code == 429:
        return "rejected"

    if 200 <= status_code < 400:
        return "success"

    if 400 <= status_code < 500:
        return "client_error"

    if 500 <= status_code < 600:
        return "server_error"

    return "other"


async def metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Record HTTP compatibility and Phase 11 execution metrics."""

    if request.url.path == "/metrics":
        return await call_next(request)

    metrics = getattr(
        request.app.state,
        "reliability_metrics",
        None,
    )

    if not isinstance(metrics, ReliabilityMetrics):
        metrics = get_reliability_metrics()

    start = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start

        metrics.observe_execution(
            endpoint=_route_template(request),
            duration_s=elapsed,
            outcome=_http_outcome_for_status(status_code),
            method=request.method,
            status_code=status_code,
        )

def metrics_endpoint(request: Request) -> Response:
    """Render the Prometheus exposition format. Refreshes runtime gauges first."""
    state = request.app.state
    GRAPH_LOADED.set(1 if getattr(state, "graph_loaded", False) else 0)
    SNAP_INDEX_LOADED.set(1 if getattr(state, "snap_index", None) is not None else 0)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
