# tests/test_phase11_endpoint_regression.py

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import (
    APP_VERSION,
    PROJECT_PHASE_CODE,
    PROJECT_PHASE_NAME,
    app,
)


def test_repeated_lifespan_cycles_do_not_reuse_shutdown_state() -> None:
    with TestClient(app) as first_client:
        first_liveness = first_client.get("/health/live")
        first_readiness = first_client.get("/health/ready")

        assert first_liveness.status_code == 200
        assert first_liveness.json()["status"] == "alive"

        assert first_readiness.status_code in {
            200,
            503,
        }
        assert (
            first_readiness.json()["status"]
            != "shutting_down"
        )

    first_shutdown_snapshot = asyncio.run(
        app.state.resilience_state.snapshot()
    )

    assert first_shutdown_snapshot.shutdown_requested is True
    assert first_shutdown_snapshot.shutdown_complete is True

    # Starting another lifespan in the same interpreter must reset the
    # previous lifecycle and limiter closure.
    with TestClient(app) as second_client:
        second_liveness = second_client.get("/health/live")
        second_readiness = second_client.get("/health/ready")

        assert second_liveness.status_code == 200
        assert second_liveness.json()["status"] == "alive"

        second_payload = second_readiness.json()

        assert second_payload["status"] != "shutting_down"
        assert second_payload["shutting_down"] is False
        assert second_payload["startup_complete"] is True
        assert second_payload["accepting_requests"] is True

        limiter_snapshot = asyncio.run(
            app.state.concurrency_limiter.snapshot()
        )

        assert limiter_snapshot.accepting_requests is True
        assert limiter_snapshot.close_reason is None


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous endpoint regression tests with asyncio."""

    return "asyncio"


@pytest.fixture
async def client() -> httpx.AsyncClient:
    """
    Create an in-process HTTP client without starting the heavy graph
    lifespan.

    These tests validate endpoint registration and operational contracts,
    not graph initialization or routing correctness.
    """

    transport = httpx.ASGITransport(
        app=app,
        raise_app_exceptions=True,
    )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client


def _api_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
    ]


def _route_method_pairs() -> set[tuple[str, str]]:
    return {
        (
            route.path,
            method,
        )
        for route in _api_routes()
        for method in route.methods
    }


def _route_for(
    path: str,
    method: str,
) -> APIRoute:
    normalized_method = method.upper()

    matches = [
        route
        for route in _api_routes()
        if route.path == path
        and normalized_method in route.methods
    ]

    assert len(matches) == 1, (
        f"Expected exactly one route for "
        f"{normalized_method} {path}, found {len(matches)}"
    )

    return matches[0]


def test_phase11_project_metadata_is_current() -> None:
    assert APP_VERSION == "0.1.0"

    assert PROJECT_PHASE_CODE == "tier4_phase11"

    assert PROJECT_PHASE_NAME == (
        "Tier 4 Phase 11 - Production Reliability "
        "and Concurrency Hardening"
    )


def test_all_required_phase11_routes_are_registered() -> None:
    registered = _route_method_pairs()

    required = {
        ("GET", "/"),
        ("GET", "/health"),
        ("GET", "/health/live"),
        ("GET", "/health/ready"),
        ("GET", "/metrics"),
        ("GET", "/graph/stats"),
        ("GET", "/graph/validate"),
        ("GET", "/graph/snap"),
        ("GET", "/route"),
        ("GET", "/route/compare"),
        ("POST", "/matrix"),
        ("POST", "/vrp/greedy"),
        ("POST", "/vrp/compare"),
        ("POST", "/vrp/compare/advanced"),
        ("POST", "/dispatch/compare"),
    }

    normalized_registered = {
        (
            method,
            path,
        )
        for path, method in registered
    }

    missing = required - normalized_registered

    assert missing == set(), (
        "Required Phase 11 endpoints are missing: "
        f"{sorted(missing)}"
    )


def test_phase10_business_endpoints_are_preserved() -> None:
    """
    Phase 11 hardening must not remove the working Phase 10 API surface.
    """

    registered = _route_method_pairs()

    preserved_routes = {
        ("/graph/stats", "GET"),
        ("/graph/validate", "GET"),
        ("/graph/snap", "GET"),
        ("/route", "GET"),
        ("/route/compare", "GET"),
        ("/matrix", "POST"),
        ("/vrp/greedy", "POST"),
        ("/vrp/compare", "POST"),
        ("/vrp/compare/advanced", "POST"),
        ("/dispatch/compare", "POST"),
    }

    assert preserved_routes <= registered


def test_phase11_operational_endpoints_are_registered() -> None:
    registered = _route_method_pairs()

    operational_routes = {
        ("/health", "GET"),
        ("/health/live", "GET"),
        ("/health/ready", "GET"),
        ("/metrics", "GET"),
    }

    assert operational_routes <= registered


def test_no_duplicate_api_route_method_pairs() -> None:
    pairs = [
        (
            route.path,
            method,
        )
        for route in _api_routes()
        for method in route.methods
    ]

    counts = Counter(pairs)

    duplicates = {
        pair: count
        for pair, count in counts.items()
        if count > 1
    }

    assert duplicates == {}, (
        "Duplicate API route registrations detected: "
        f"{duplicates}"
    )


def test_required_routes_have_operation_ids() -> None:
    routes_to_check = {
        ("/health/live", "GET"),
        ("/health/ready", "GET"),
        ("/graph/stats", "GET"),
        ("/route", "GET"),
        ("/matrix", "POST"),
        ("/vrp/compare/advanced", "POST"),
        ("/dispatch/compare", "POST"),
    }

    for path, method in routes_to_check:
        route = _route_for(path, method)

        assert route.name
        assert route.unique_id


def test_phase11_reliability_middlewares_are_registered() -> None:
    middleware_names = {
        middleware.cls.__name__
        for middleware in app.user_middleware
    }

    required_middleware = {
        "LifecycleGuardMiddleware",
        "ConcurrencyControlMiddleware",
        "RequestTimeoutMiddleware",
    }

    missing = required_middleware - middleware_names

    assert missing == set(), (
        "Required Phase 11 middleware is missing: "
        f"{sorted(missing)}"
    )


@pytest.mark.anyio
async def test_root_endpoint_reports_phase11_contract(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["service"] == "cityroute"
    assert payload["version"] == APP_VERSION

    assert payload["phase"] == PROJECT_PHASE_NAME
    assert payload["phase_code"] == PROJECT_PHASE_CODE

    assert payload["health"] == "/health"
    assert payload["liveness"] == "/health/live"
    assert payload["readiness"] == "/health/ready"
    assert payload["metrics"] == "/metrics"

    assert payload["route"] == "/route"
    assert payload["route_compare"] == "/route/compare"
    assert payload["matrix"] == "/matrix"
    assert payload["vrp_greedy"] == "/vrp/greedy"
    assert payload["vrp_compare"] == "/vrp/compare"
    assert (
        payload["vrp_advanced_compare"]
        == "/vrp/compare/advanced"
    )
    assert (
        payload["dispatch_compare"]
        == "/dispatch/compare"
    )

    algorithms = payload["dispatch_matrix_algorithms"]

    assert set(algorithms) == {
        "haversine",
        "source_dijkstra",
    }

    assert "reliability" in payload["phase11_goal"].lower()
    assert "concurrency" in payload["phase11_goal"].lower()


@pytest.mark.anyio
async def test_liveness_endpoint_remains_available(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "alive"
    assert payload["phase"] == PROJECT_PHASE_CODE
    assert payload["uptime_s"] >= 0.0

    assert set(payload) == {
        "status",
        "phase",
        "uptime_s",
    }


@pytest.mark.anyio
async def test_readiness_endpoint_returns_controlled_contract(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health/ready")

    # Without lifespan initialization this can be not-ready. In a running
    # application it can be ready or degraded under Redis fail-open mode.
    assert response.status_code in {
        200,
        503,
    }

    payload = response.json()

    assert payload["status"] in {
        "ready",
        "degraded",
        "not_ready",
        "shutting_down",
    }

    assert isinstance(payload["ready"], bool)
    assert payload["phase"] == PROJECT_PHASE_CODE
    assert payload["uptime_s"] >= 0.0

    assert isinstance(
        payload["startup_complete"],
        bool,
    )
    assert isinstance(
        payload["accepting_requests"],
        bool,
    )
    assert isinstance(
        payload["shutting_down"],
        bool,
    )

    assert set(payload["components"]) == {
        "graph",
        "snap_index",
        "dispatch_adjacency",
        "redis",
    }

    assert isinstance(
        payload["degraded_dependencies"],
        list,
    )
    assert isinstance(
        payload["failure_reasons"],
        list,
    )

    if response.status_code == 200:
        assert payload["ready"] is True
        assert payload["status"] in {
            "ready",
            "degraded",
        }
    else:
        assert payload["ready"] is False
        assert payload["status"] in {
            "not_ready",
            "shutting_down",
        }


@pytest.mark.anyio
async def test_legacy_health_endpoint_remains_compatible(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] in {
        "ok",
        "degraded",
        "starting",
        "shutting_down",
    }

    assert isinstance(payload["graph_loaded"], bool)
    assert payload["uptime_s"] >= 0.0

    assert set(payload) == {
        "status",
        "graph_loaded",
        "uptime_s",
    }


@pytest.mark.anyio
async def test_metrics_endpoint_remains_scrapeable(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/metrics")

    assert response.status_code == 200

    content_type = response.headers["content-type"]

    assert content_type.startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["x-content-type-options"]
        == "nosniff"
    )

    body = response.text

    assert "# HELP" in body
    assert "# TYPE" in body
    assert "cityroute_" in body


def test_openapi_preserves_business_endpoint_schema() -> None:
    schema: dict[str, Any] = app.openapi()
    paths = schema["paths"]

    required_operations = {
        "/health": "get",
        "/health/live": "get",
        "/health/ready": "get",
        "/graph/stats": "get",
        "/graph/validate": "get",
        "/graph/snap": "get",
        "/route": "get",
        "/route/compare": "get",
        "/matrix": "post",
        "/vrp/greedy": "post",
        "/vrp/compare": "post",
        "/vrp/compare/advanced": "post",
        "/dispatch/compare": "post",
    }

    for path, method in required_operations.items():
        assert path in paths, (
            f"OpenAPI path missing: {path}"
        )
        assert method in paths[path], (
            f"OpenAPI operation missing: "
            f"{method.upper()} {path}"
        )


def test_openapi_has_unique_operation_ids() -> None:
    schema: dict[str, Any] = app.openapi()

    operation_ids: list[str] = []

    for path_data in schema["paths"].values():
        for method, operation in path_data.items():
            if method not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
                "trace",
            }:
                continue

            operation_id = operation.get("operationId")

            assert operation_id is not None
            operation_ids.append(operation_id)

    counts = Counter(operation_ids)

    duplicates = {
        operation_id: count
        for operation_id, count in counts.items()
        if count > 1
    }

    assert duplicates == {}, (
        "Duplicate OpenAPI operation IDs detected: "
        f"{duplicates}"
    )