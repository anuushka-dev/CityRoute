# app/observability/metrics.py

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.requests import Request
from starlette.responses import Response

# A dedicated registry keeps CityRoute metrics isolated and makes tests deterministic.
REGISTRY = CollectorRegistry()

REQUEST_COUNT = Counter(
    "cityroute_http_requests_total",
    "Total HTTP requests handled by CityRoute.",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)

REQUEST_LATENCY = Histogram(
    "cityroute_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path"),
    # Buckets tuned for a routing API: sub-ms snaps up to multi-second matrices.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

GRAPH_LOADED = Gauge(
    "cityroute_graph_loaded",
    "Whether the road graph is loaded (1) or not (0).",
    registry=REGISTRY,
)

SNAP_INDEX_LOADED = Gauge(
    "cityroute_snap_index_loaded",
    "Whether the BallTree snap index is loaded (1) or not (0).",
    registry=REGISTRY,
)


def _route_template(request: Request) -> str:
    """Return the matched route pattern (e.g. '/route/compare') to keep label
    cardinality bounded. Falls back to the raw path, then 'unmatched'."""
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    if path_format:
        return str(path_format)
    return request.url.path or "unmatched"


async def metrics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Time every request and record count + latency. Never swallow app errors."""
    # Do not instrument the scrape endpoint itself.
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        path = _route_template(request)
        REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        REQUEST_COUNT.labels(request.method, path, str(status_code)).inc()


def metrics_endpoint(request: Request) -> Response:
    """Render the Prometheus exposition format. Refreshes runtime gauges first."""
    state = request.app.state
    GRAPH_LOADED.set(1 if getattr(state, "graph_loaded", False) else 0)
    SNAP_INDEX_LOADED.set(1 if getattr(state, "snap_index", None) is not None else 0)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
