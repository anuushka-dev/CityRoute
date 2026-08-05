# tests/test_readiness.py

from __future__ import annotations

from time import perf_counter

import httpx
import pytest
from fastapi import FastAPI

from app.api.health import router as health_router
from app.infrastructure.resilience_state import ResilienceState
from app.services.readiness_service import (
    ReadinessPolicy,
    ReadinessService,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run async readiness tests with asyncio only."""

    return "asyncio"


def _build_app(
    *,
    state: ResilienceState | None = None,
    policy: ReadinessPolicy | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)

    app.state.phase = "tier4_phase11"
    app.state.started_at = perf_counter() - 1.0

    if state is not None:
        readiness_policy = policy or ReadinessPolicy()

        app.state.resilience_state = state
        app.state.readiness_policy = readiness_policy
        app.state.readiness_service = ReadinessService(
            resilience_state=state,
            phase="tier4_phase11",
            policy=readiness_policy,
        )

    return app


async def _get(
    app: FastAPI,
    path: str,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.get(path)


async def _initialize_required_components(
    state: ResilienceState,
    *,
    graph_ready: bool = True,
    snap_index_ready: bool = True,
    adjacency_ready: bool = True,
    redis_ready: bool = True,
) -> None:
    await state.mark_startup_started()

    if graph_ready:
        await state.set_graph_ready(True)

    if snap_index_ready:
        await state.set_snap_index_ready(True)

    if adjacency_ready:
        await state.set_dispatch_adjacency_ready(True)

    if redis_ready:
        await state.mark_redis_success()

    await state.mark_startup_complete()


@pytest.mark.anyio
async def test_readiness_returns_503_before_startup() -> None:
    state = ResilienceState()
    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["phase"] == "tier4_phase11"

    assert payload["startup_complete"] is False
    assert payload["accepting_requests"] is False
    assert payload["shutting_down"] is False

    assert payload["components"] == {
        "graph": "not_initialized",
        "snap_index": "not_initialized",
        "dispatch_adjacency": "not_initialized",
        "redis": "not_required",
    }

    assert "startup_incomplete" in payload["failure_reasons"]
    assert (
        "graph_not_ready:not_initialized"
        in payload["failure_reasons"]
    )
    assert (
        "snap_index_not_ready:not_initialized"
        in payload["failure_reasons"]
    )
    assert (
        "dispatch_adjacency_not_ready:not_initialized"
        in payload["failure_reasons"]
    )


@pytest.mark.anyio
async def test_readiness_returns_200_when_fully_ready() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 200

    assert payload["status"] == "ready"
    assert payload["ready"] is True
    assert payload["startup_complete"] is True
    assert payload["accepting_requests"] is True
    assert payload["shutting_down"] is False

    assert payload["components"] == {
        "graph": "ready",
        "snap_index": "ready",
        "dispatch_adjacency": "ready",
        "redis": "ready",
    }

    assert payload["degraded_dependencies"] == []
    assert payload["failure_reasons"] == []


@pytest.mark.anyio
async def test_readiness_is_degraded_when_redis_fails_open() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)

    await state.mark_redis_failure(
        "connection_refused",
        unavailable=True,
    )

    app = _build_app(
        state=state,
        policy=ReadinessPolicy(
            require_graph=True,
            require_snap_index=True,
            require_dispatch_adjacency=True,
            require_redis=False,
            redis_fail_open=True,
        ),
    )

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 200

    assert payload["status"] == "degraded"
    assert payload["ready"] is True
    assert payload["accepting_requests"] is True

    assert payload["components"]["graph"] == "ready"
    assert payload["components"]["snap_index"] == "ready"
    assert payload["components"]["dispatch_adjacency"] == "ready"
    assert payload["components"]["redis"] == "degraded"

    assert payload["degraded_dependencies"] == ["redis"]
    assert payload["failure_reasons"] == []


@pytest.mark.anyio
async def test_readiness_returns_503_when_redis_is_required() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)

    await state.mark_redis_failure(
        "connection_refused",
        unavailable=True,
    )

    app = _build_app(
        state=state,
        policy=ReadinessPolicy(
            require_graph=True,
            require_snap_index=True,
            require_dispatch_adjacency=True,
            require_redis=True,
            redis_fail_open=False,
        ),
    )

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["components"]["redis"] == "unavailable"
    assert payload["degraded_dependencies"] == []

    assert (
        "redis_not_ready:unavailable"
        in payload["failure_reasons"]
    )


@pytest.mark.anyio
async def test_readiness_returns_503_when_graph_is_missing() -> None:
    state = ResilienceState()

    await _initialize_required_components(
        state,
        graph_ready=False,
    )

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["startup_complete"] is True
    assert payload["accepting_requests"] is True

    assert payload["components"]["graph"] == "not_initialized"
    assert payload["components"]["snap_index"] == "ready"
    assert payload["components"]["dispatch_adjacency"] == "ready"

    assert (
        "graph_not_ready:not_initialized"
        in payload["failure_reasons"]
    )


@pytest.mark.anyio
async def test_readiness_returns_503_when_snap_index_is_missing() -> None:
    state = ResilienceState()

    await _initialize_required_components(
        state,
        snap_index_ready=False,
    )

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["components"]["snap_index"] == "not_initialized"

    assert (
        "snap_index_not_ready:not_initialized"
        in payload["failure_reasons"]
    )


@pytest.mark.anyio
async def test_readiness_returns_503_when_adjacency_is_missing() -> None:
    state = ResilienceState()

    await _initialize_required_components(
        state,
        adjacency_ready=False,
    )

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert (
        payload["components"]["dispatch_adjacency"]
        == "not_initialized"
    )

    assert (
        "dispatch_adjacency_not_ready:not_initialized"
        in payload["failure_reasons"]
    )


@pytest.mark.anyio
async def test_readiness_returns_503_when_admission_is_disabled() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)
    await state.set_accepting_requests(False)

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["startup_complete"] is True
    assert payload["accepting_requests"] is False
    assert payload["shutting_down"] is False

    assert payload["failure_reasons"] == [
        "not_accepting_requests"
    ]


@pytest.mark.anyio
async def test_readiness_returns_503_during_shutdown() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)
    await state.begin_shutdown()

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "shutting_down"
    assert payload["ready"] is False
    assert payload["accepting_requests"] is False
    assert payload["shutting_down"] is True

    assert payload["failure_reasons"] == [
        "service_shutting_down"
    ]


@pytest.mark.anyio
async def test_readiness_fallback_is_safely_not_ready() -> None:
    app = _build_app()

    app.state.graph_loaded = True
    app.state.snap_index = object()
    app.state.dispatch_adjacency = object()

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 503

    assert payload["status"] == "not_ready"
    assert payload["ready"] is False
    assert payload["startup_complete"] is False
    assert payload["accepting_requests"] is False

    assert payload["components"] == {
        "graph": "ready",
        "snap_index": "ready",
        "dispatch_adjacency": "ready",
        "redis": "not_initialized",
    }

    assert payload["failure_reasons"] == [
        "readiness_service_not_initialized"
    ]


@pytest.mark.anyio
async def test_readiness_response_has_exact_contract() -> None:
    state = ResilienceState()

    await _initialize_required_components(state)

    app = _build_app(state=state)

    response = await _get(app, "/health/ready")
    payload = response.json()

    assert response.status_code == 200

    assert set(payload) == {
        "status",
        "ready",
        "phase",
        "uptime_s",
        "startup_complete",
        "accepting_requests",
        "shutting_down",
        "components",
        "degraded_dependencies",
        "failure_reasons",
    }

    assert set(payload["components"]) == {
        "graph",
        "snap_index",
        "dispatch_adjacency",
        "redis",
    }

    assert payload["uptime_s"] >= 0.0