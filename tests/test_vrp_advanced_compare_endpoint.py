from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import vrp as vrp_api
from app.main import app
from app.schemas.vrp_advanced_compare import AdvancedCompareResponse


def _valid_payload() -> dict[str, Any]:
    return {
        "start": {"lat": 26.4499, "lon": 80.3319},
        "stops": [
            {"lat": 26.4520, "lon": 80.3330},
            {"lat": 26.4550, "lon": 80.3350},
            {"lat": 26.4580, "lon": 80.3380},
        ],
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "two_opt_max_iterations": 100,
        "two_opt_improvement_tolerance_m": 0.001,
        "lns_max_iterations": 50,
        "lns_destroy_fraction": 0.30,
        "lns_no_improvement_limit": 20,
        "lns_random_seed": 42,
        "keep_trace": True,
    }


def _fake_advanced_response() -> AdvancedCompareResponse:
    return AdvancedCompareResponse(
        status="ok",
        phase="tier3_phase8",
        matrix_algorithm="source_dijkstra",
        stop_count=3,
        return_to_start=False,
        greedy={
            "algorithm": "nearest_neighbor_greedy",
            "optimized_order": [0, 1, 2],
            "total_distance_m": 3000.0,
            "legs": [
                {
                    "from_type": "start",
                    "from_index": None,
                    "to_type": "stop",
                    "to_index": 0,
                    "distance_m": 1000.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 0,
                    "to_type": "stop",
                    "to_index": 1,
                    "distance_m": 1000.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 1,
                    "to_type": "stop",
                    "to_index": 2,
                    "distance_m": 1000.0,
                },
            ],
            "optimization_time_ms": 0.05,
        },
        two_opt={
            "algorithm": "two_opt",
            "optimized_order": [0, 2, 1],
            "total_distance_m": 2700.0,
            "initial_distance_m": 3000.0,
            "distance_saved_m": 300.0,
            "improvement_pct": 10.0,
            "iterations_run": 2,
            "swaps_applied": 1,
            "converged": True,
            "legs": [
                {
                    "from_type": "start",
                    "from_index": None,
                    "to_type": "stop",
                    "to_index": 0,
                    "distance_m": 1000.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 0,
                    "to_type": "stop",
                    "to_index": 2,
                    "distance_m": 700.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 2,
                    "to_type": "stop",
                    "to_index": 1,
                    "distance_m": 1000.0,
                },
            ],
            "optimization_time_ms": 0.10,
            "trace": [
                {
                    "iteration": 1,
                    "best_distance_m": 3000.0,
                    "improved": False,
                },
                {
                    "iteration": 2,
                    "best_distance_m": 2700.0,
                    "improved": True,
                },
            ],
        },
        lns={
            "algorithm": "large_neighborhood_search",
            "optimized_order": [2, 0, 1],
            "total_distance_m": 2500.0,
            "initial_distance_m": 2700.0,
            "distance_saved_m": 200.0,
            "improvement_pct": 7.407,
            "iterations_run": 10,
            "improvements_applied": 1,
            "converged": True,
            "random_seed": 42,
            "legs": [
                {
                    "from_type": "start",
                    "from_index": None,
                    "to_type": "stop",
                    "to_index": 2,
                    "distance_m": 800.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 2,
                    "to_type": "stop",
                    "to_index": 0,
                    "distance_m": 800.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 0,
                    "to_type": "stop",
                    "to_index": 1,
                    "distance_m": 900.0,
                },
            ],
            "optimization_time_ms": 0.30,
            "trace": [
                {
                    "iteration": 1,
                    "best_distance_m": 2700.0,
                    "candidate_distance_m": 2700.0,
                    "improved": False,
                    "removed_count": 1,
                },
                {
                    "iteration": 2,
                    "best_distance_m": 2500.0,
                    "candidate_distance_m": 2500.0,
                    "improved": True,
                    "removed_count": 1,
                },
            ],
        },
        comparison={
            "two_opt_vs_greedy_distance_saved_m": 300.0,
            "two_opt_vs_greedy_improvement_pct": 10.0,
            "lns_vs_two_opt_distance_saved_m": 200.0,
            "lns_vs_two_opt_improvement_pct": 7.407,
            "lns_vs_greedy_distance_saved_m": 500.0,
            "lns_vs_greedy_improvement_pct": 16.667,
            "two_opt_non_regression": True,
            "lns_non_regression": True,
        },
        matrix_generation_time_ms=2.0,
        cache_used=True,
        cache_status="hit",
        cache_hits=1,
        cache_misses=0,
        total_time_ms=3.0,
    )


@pytest.fixture(autouse=True)
def graph_ready_state():
    original_graph_loaded = getattr(app.state, "graph_loaded", None)
    original_graph = getattr(app.state, "graph", None)
    original_snap_index = getattr(app.state, "snap_index", None)

    app.state.graph_loaded = True
    app.state.graph = object()
    app.state.snap_index = object()

    yield

    app.state.graph_loaded = original_graph_loaded
    app.state.graph = original_graph
    app.state.snap_index = original_snap_index


def test_advanced_compare_endpoint_returns_lns_payload(monkeypatch: pytest.MonkeyPatch):
    async def fake_build_advanced_compare_response(*args: Any, **kwargs: Any):
        return _fake_advanced_response()

    monkeypatch.setattr(
        vrp_api,
        "build_advanced_compare_response",
        fake_build_advanced_compare_response,
    )

    with TestClient(app) as client:
        response = client.post("/vrp/compare/advanced", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["phase"] == "tier3_phase8"
    assert body["stop_count"] == 3

    assert body["greedy"]["algorithm"] == "nearest_neighbor_greedy"
    assert body["two_opt"]["algorithm"] == "two_opt"
    assert body["lns"]["algorithm"] == "large_neighborhood_search"

    assert body["comparison"]["two_opt_non_regression"] is True
    assert body["comparison"]["lns_non_regression"] is True

    assert body["lns"]["random_seed"] == 42
    assert len(body["lns"]["trace"]) == 2


def test_advanced_compare_endpoint_requires_graph_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    async def should_not_reach_service(*args: Any, **kwargs: Any):
        raise AssertionError("advanced compare service should not run when graph is not ready")

    monkeypatch.setattr(
        vrp_api,
        "build_advanced_compare_response",
        should_not_reach_service,
    )

    with TestClient(app) as client:
        app.state.graph_loaded = False
        app.state.graph = None
        app.state.snap_index = object()

        response = client.post(
            "/vrp/compare/advanced",
            json=_valid_payload(),
        )
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "Graph not loaded"


def test_advanced_compare_endpoint_validates_max_24_stops():
    payload = _valid_payload()
    payload["stops"] = [{"lat": 26.45, "lon": 80.33} for _ in range(25)]

    with TestClient(app) as client:
        response = client.post("/vrp/compare/advanced", json=payload)

    assert response.status_code == 422


def test_advanced_compare_endpoint_validates_lns_parameters():
    payload = _valid_payload()
    payload["lns_destroy_fraction"] = 1.5

    with TestClient(app) as client:
        response = client.post("/vrp/compare/advanced", json=payload)

    assert response.status_code == 422