# tests/test_vrp_greedy_endpoint.py

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _payload_with_stops(stop_count: int) -> dict:
    base_stops = [
        {"lat": 26.45, "lon": 80.35},
        {"lat": 26.46, "lon": 80.34},
        {"lat": 26.47, "lon": 80.33},
        {"lat": 26.48, "lon": 80.32},
        {"lat": 26.49, "lon": 80.31},
    ]

    return {
        "start": {"lat": 26.44, "lon": 80.30},
        "stops": base_stops[:stop_count],
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
    }


def test_vrp_greedy_endpoint_registered_in_openapi():
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]

    assert "/vrp/greedy" in paths


def test_vrp_greedy_rejects_empty_stops_with_422():
    payload = {
        "start": {"lat": 26.44, "lon": 80.30},
        "stops": [],
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/vrp/greedy", json=payload)

    assert response.status_code == 422


def test_vrp_greedy_rejects_invalid_latitude_with_422():
    payload = {
        "start": {"lat": 200.0, "lon": 80.30},
        "stops": [
            {"lat": 26.45, "lon": 80.35},
        ],
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/vrp/greedy", json=payload)

    assert response.status_code == 422


def test_vrp_greedy_rejects_invalid_matrix_algorithm_with_422():
    payload = {
        "start": {"lat": 26.44, "lon": 80.30},
        "stops": [
            {"lat": 26.45, "lon": 80.35},
        ],
        "return_to_start": False,
        "matrix_algorithm": "fake_algorithm",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/vrp/greedy", json=payload)

    assert response.status_code == 422


def test_vrp_greedy_rejects_more_than_24_stops_with_422():
    stops = [
        {"lat": 26.45, "lon": 80.35}
        for _ in range(25)
    ]

    payload = {
        "start": {"lat": 26.44, "lon": 80.30},
        "stops": stops,
        "return_to_start": False,
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/vrp/greedy", json=payload)

    assert response.status_code == 422


def test_vrp_greedy_graph_missing_returns_503():
    payload = _payload_with_stops(1)

    with TestClient(app) as client:
        original_graph_loaded = getattr(client.app.state, "graph_loaded", None)
        original_graph = getattr(client.app.state, "graph", None)

        client.app.state.graph_loaded = False
        client.app.state.graph = None

        try:
            response = client.post("/vrp/greedy", json=payload)

            assert response.status_code == 503
            assert response.json()["detail"]["error"] == "Graph not loaded"

        finally:
            client.app.state.graph_loaded = original_graph_loaded
            client.app.state.graph = original_graph


def test_vrp_greedy_snap_index_missing_returns_503():
    with TestClient(app) as client:
        original_snap_index = getattr(client.app.state, "snap_index", None)

        client.app.state.snap_index = None

        payload = _payload_with_stops(1)

        try:
            response = client.post("/vrp/greedy", json=payload)

            assert response.status_code == 503
            assert response.json()["detail"]["error"] == "Snap index not loaded"

        finally:
            client.app.state.snap_index = original_snap_index