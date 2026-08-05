# tests/test_liveness.py

from __future__ import annotations

from collections.abc import Generator
from time import perf_counter

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router as health_router


class ExplodingReadinessService:
    """
    Test double proving that liveness does not evaluate readiness.

    Any accidental readiness call makes the test fail immediately.
    """

    async def get_readiness(self) -> None:
        raise AssertionError(
            "The liveness endpoint must not evaluate readiness"
        )


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(health_router)

    test_app.state.phase = "tier4_phase11"
    test_app.state.started_at = perf_counter() - 2.0

    return test_app


@pytest.fixture
def client(
    app: FastAPI,
) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def test_liveness_returns_expected_contract(
    client: TestClient,
) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/json"
    )

    payload = response.json()

    assert set(payload) == {
        "status",
        "phase",
        "uptime_s",
    }
    assert payload["status"] == "alive"
    assert payload["phase"] == "tier4_phase11"
    assert payload["uptime_s"] >= 0.0


def test_liveness_does_not_require_graph_or_redis(
    app: FastAPI,
) -> None:
    app.state.graph_loaded = False
    app.state.snap_index = None
    app.state.dispatch_graph_adjacency = None
    app.state.dispatch_road_cache_available = False

    app.state.readiness_service = ExplodingReadinessService()

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_liveness_remains_alive_during_startup(
    app: FastAPI,
) -> None:
    app.state.startup_complete = False
    app.state.accepting_requests = False
    app.state.graph_loaded = False

    with TestClient(app) as client:
        response = client.get("/health/live")

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "alive"
    assert payload["phase"] == "tier4_phase11"


def test_liveness_remains_alive_during_shutdown(
    app: FastAPI,
) -> None:
    app.state.shutdown_requested = True
    app.state.shutdown_complete = False
    app.state.accepting_requests = False

    app.state.readiness_service = ExplodingReadinessService()

    with TestClient(app) as client:
        response = client.get("/health/live")

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "alive"
    assert payload["uptime_s"] >= 0.0


def test_liveness_uses_default_phase_when_missing(
    app: FastAPI,
) -> None:
    del app.state.phase

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["phase"] == "tier4_phase11"


def test_liveness_handles_invalid_started_at_safely(
    app: FastAPI,
) -> None:
    app.state.started_at = "invalid-start-time"

    with TestClient(app) as client:
        response = client.get("/health/live")

    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "alive"
    assert payload["uptime_s"] == 0.0