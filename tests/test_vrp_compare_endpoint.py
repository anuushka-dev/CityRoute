# tests/test_vrp_compare_endpoint.py

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.vrp import router as vrp_router
from app.services.vrp_compare_service import VrpCompareServiceError


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(vrp_router)

    app.state.graph_loaded = True
    app.state.graph = object()
    app.state.snap_index = object()

    return app


def _valid_payload() -> dict[str, Any]:
    return {
        "start": {
            "id": "depot",
            "lat": 26.4499,
            "lon": 80.3319,
        },
        "stops": [
            {
                "id": "stop_0",
                "lat": 26.4600,
                "lon": 80.3400,
            },
            {
                "id": "stop_1",
                "lat": 26.4700,
                "lon": 80.3500,
            },
            {
                "id": "stop_2",
                "lat": 26.4800,
                "lon": 80.3600,
            },
        ],
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "two_opt_max_iterations": 100,
        "improvement_tolerance_m": 0.001,
        "keep_trace": True,
    }


def _fake_compare_response() -> dict[str, Any]:
    return {
        "status": "ok",
        "phase": "tier2_phase7",
        "comparison": "greedy_vs_two_opt",
        "matrix_algorithm": "source_dijkstra",
        "stop_count": 3,
        "return_to_start": False,
        "greedy": {
            "algorithm": "nearest_neighbor_greedy",
            "optimized_order": [0, 1, 2],
            "total_distance_m": 21.0,
            "legs": [
                {
                    "from_type": "start",
                    "from_index": None,
                    "to_type": "stop",
                    "to_index": 0,
                    "distance_m": 10.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 0,
                    "to_type": "stop",
                    "to_index": 1,
                    "distance_m": 10.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 1,
                    "to_type": "stop",
                    "to_index": 2,
                    "distance_m": 1.0,
                },
            ],
            "optimization_time_ms": 0.05,
            "iterations": 0,
            "swaps_applied": 0,
            "converged": True,
        },
        "two_opt": {
            "algorithm": "two_opt",
            "optimized_order": [1, 2, 0],
            "total_distance_m": 3.0,
            "legs": [
                {
                    "from_type": "start",
                    "from_index": None,
                    "to_type": "stop",
                    "to_index": 1,
                    "distance_m": 1.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 1,
                    "to_type": "stop",
                    "to_index": 2,
                    "distance_m": 1.0,
                },
                {
                    "from_type": "stop",
                    "from_index": 2,
                    "to_type": "stop",
                    "to_index": 0,
                    "distance_m": 1.0,
                },
            ],
            "optimization_time_ms": 0.15,
            "iterations": 3,
            "swaps_applied": 2,
            "converged": True,
        },
        "improvement": {
            "baseline_distance_m": 21.0,
            "optimized_distance_m": 3.0,
            "distance_saved_m": 18.0,
            "improvement_pct": 85.714,
            "improved": True,
            "non_regression": True,
        },
        "convergence_trace": [
            {
                "iteration": 0,
                "distance_m": 21.0,
                "improved": False,
                "swap_i": None,
                "swap_j": None,
            },
            {
                "iteration": 1,
                "distance_m": 12.0,
                "improved": True,
                "swap_i": 0,
                "swap_j": 1,
            },
            {
                "iteration": 2,
                "distance_m": 3.0,
                "improved": True,
                "swap_i": 1,
                "swap_j": 2,
            },
            {
                "iteration": 3,
                "distance_m": 3.0,
                "improved": False,
                "swap_i": None,
                "swap_j": None,
            },
        ],
        "matrix_generation_time_ms": 4.0,
        "total_time_ms": 5.0,
        "cache_used": True,
        "cache_hits": 1,
        "cache_misses": 0,
    }


def test_vrp_compare_endpoint_returns_greedy_vs_two_opt(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _test_app()
    client = TestClient(app)

    captured_kwargs: dict[str, Any] = {}

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return _fake_compare_response()

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    response = client.post("/vrp/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["phase"] == "tier2_phase7"
    assert body["comparison"] == "greedy_vs_two_opt"

    assert body["matrix_algorithm"] == "source_dijkstra"
    assert body["stop_count"] == 3
    assert body["return_to_start"] is False

    assert body["greedy"]["algorithm"] == "nearest_neighbor_greedy"
    assert body["greedy"]["optimized_order"] == [0, 1, 2]
    assert body["greedy"]["total_distance_m"] == 21.0

    assert body["two_opt"]["algorithm"] == "two_opt"
    assert body["two_opt"]["optimized_order"] == [1, 2, 0]
    assert body["two_opt"]["total_distance_m"] == 3.0
    assert body["two_opt"]["swaps_applied"] == 2
    assert body["two_opt"]["converged"] is True

    assert body["improvement"]["baseline_distance_m"] == 21.0
    assert body["improvement"]["optimized_distance_m"] == 3.0
    assert body["improvement"]["distance_saved_m"] == 18.0
    assert body["improvement"]["improvement_pct"] == 85.714
    assert body["improvement"]["improved"] is True
    assert body["improvement"]["non_regression"] is True

    assert body["cache_used"] is True
    assert body["cache_hits"] == 1
    assert body["cache_misses"] == 0

    assert captured_kwargs["matrix_algorithm"] == "source_dijkstra"
    assert captured_kwargs["use_cache"] is True
    assert captured_kwargs["return_to_start"] is False
    assert captured_kwargs["two_opt_max_iterations"] == 100


def test_vrp_compare_endpoint_supports_return_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _test_app()
    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        response = _fake_compare_response()
        response["return_to_start"] = kwargs["return_to_start"]
        return response

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    payload = _valid_payload()
    payload["return_to_start"] = True

    response = client.post("/vrp/compare", json=payload)

    assert response.status_code == 200
    assert response.json()["return_to_start"] is True


def test_vrp_compare_endpoint_rejects_when_graph_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(vrp_router)

    app.state.graph_loaded = False
    app.state.graph = None
    app.state.snap_index = None

    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("compute_vrp_compare should not be called")

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    response = client.post("/vrp/compare", json=_valid_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "Graph not loaded"


def test_vrp_compare_endpoint_rejects_when_snap_index_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(vrp_router)

    app.state.graph_loaded = True
    app.state.graph = object()
    app.state.snap_index = None

    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("compute_vrp_compare should not be called")

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    response = client.post("/vrp/compare", json=_valid_payload())

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "Snap index not loaded"


def test_vrp_compare_endpoint_maps_service_error_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _test_app()
    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        raise VrpCompareServiceError("bad compare input")

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    response = client.post("/vrp/compare", json=_valid_payload())

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Invalid VRP compare request"
    assert response.json()["detail"]["message"] == "bad compare input"


def test_vrp_compare_endpoint_rejects_more_than_24_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _test_app()
    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("compute_vrp_compare should not be called")

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    payload = _valid_payload()
    payload["stops"] = [
        {
            "id": f"stop_{index}",
            "lat": 26.45 + (index * 0.001),
            "lon": 80.33 + (index * 0.001),
        }
        for index in range(25)
    ]

    response = client.post("/vrp/compare", json=payload)

    assert response.status_code == 422


def test_vrp_compare_endpoint_rejects_invalid_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _test_app()
    client = TestClient(app)

    async def fake_compute_vrp_compare(**kwargs: Any) -> dict[str, Any]:
        raise AssertionError("compute_vrp_compare should not be called")

    monkeypatch.setattr(
        "app.api.vrp.compute_vrp_compare",
        fake_compute_vrp_compare,
    )

    payload = _valid_payload()
    payload["matrix_algorithm"] = "bad_algorithm"

    response = client.post("/vrp/compare", json=payload)

    assert response.status_code == 422