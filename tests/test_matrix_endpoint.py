# tests/test_matrix_endpoint.py

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.matrix import router as matrix_router
from app.models.matrix_model import MatrixResponse


def _create_test_app(
    *,
    graph_loaded: bool = True,
    graph: Any = object(),
    snap_index: Any = object(),
) -> FastAPI:
    app = FastAPI()
    app.include_router(matrix_router)

    app.state.graph_loaded = graph_loaded
    app.state.graph = graph
    app.state.snap_index = snap_index

    return app


def _valid_payload() -> dict[str, Any]:
    return {
        "locations": [
            {"id": "depot", "lat": 26.44, "lon": 80.30},
            {"id": "stop_1", "lat": 26.45, "lon": 80.35},
            {"id": "stop_2", "lat": 26.46, "lon": 80.33},
        ],
        "algorithm": "bidirectional_astar",
        "use_cache": True,
    }


def _fake_matrix_response() -> MatrixResponse:
    return MatrixResponse(
        status="ok",
        n=3,
        algorithm="bidirectional_astar",
        cache={
            "enabled": True,
            "hit": False,
            "key": "matrix:v1:test",
            "ttl_seconds": 86400,
            "error": None,
        },
        locations=[
            {"id": "depot", "lat": 26.44, "lon": 80.30},
            {"id": "stop_1", "lat": 26.45, "lon": 80.35},
            {"id": "stop_2", "lat": 26.46, "lon": 80.33},
        ],
        matrix_distance_m=[
            [0.0, 1000.0, 2000.0],
            [1100.0, 0.0, 1500.0],
            [2100.0, 1400.0, 0.0],
        ],
        matrix_eta_s=[
            [0.0, 155.44, 310.88],
            [170.98, 0.0, 233.16],
            [326.42, 217.62, 0.0],
        ],
        pair_count=9,
        computed_pairs=9,
        failed_pairs=0,
        failures=[],
        generation_time_ms=25.5,
        parallel_workers=8,
    )


def test_matrix_endpoint_returns_matrix_response(monkeypatch):
    app = _create_test_app()

    def fake_build_distance_matrix_response(payload, graph, snap_index):
        assert len(payload.locations) == 3
        assert payload.algorithm == "bidirectional_astar"
        assert payload.use_cache is True
        assert graph is not None
        assert snap_index is not None
        return _fake_matrix_response()

    monkeypatch.setattr(
        "app.api.matrix.build_distance_matrix_response",
        fake_build_distance_matrix_response,
    )

    with TestClient(app) as client:
        response = client.post("/matrix", json=_valid_payload())

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["n"] == 3
    assert data["algorithm"] == "bidirectional_astar"
    assert data["cache"]["enabled"] is True
    assert data["cache"]["hit"] is False
    assert data["pair_count"] == 9
    assert data["computed_pairs"] == 9
    assert data["failed_pairs"] == 0
    assert data["matrix_distance_m"][0][0] == 0.0
    assert data["matrix_distance_m"][1][1] == 0.0
    assert data["matrix_distance_m"][2][2] == 0.0


def test_matrix_endpoint_returns_503_when_graph_not_loaded():
    app = _create_test_app(graph_loaded=False, graph=None, snap_index=object())

    with TestClient(app) as client:
        response = client.post("/matrix", json=_valid_payload())

    assert response.status_code == 503

    data = response.json()

    assert data["detail"]["error"] == "Graph not loaded"
    assert "Distance matrix cannot be generated" in data["detail"]["message"]


def test_matrix_endpoint_returns_503_when_snap_index_missing():
    app = _create_test_app(graph_loaded=True, graph=object(), snap_index=None)

    with TestClient(app) as client:
        response = client.post("/matrix", json=_valid_payload())

    assert response.status_code == 503

    data = response.json()

    assert data["detail"]["error"] == "Snap index not loaded"
    assert "BallTree snap index" in data["detail"]["message"]


def test_matrix_endpoint_rejects_duplicate_location_ids():
    app = _create_test_app()

    payload = {
        "locations": [
            {"id": "same", "lat": 26.44, "lon": 80.30},
            {"id": "same", "lat": 26.45, "lon": 80.35},
        ],
        "algorithm": "bidirectional_astar",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/matrix", json=payload)

    assert response.status_code == 422


def test_matrix_endpoint_rejects_non_numeric_coordinate():
    app = _create_test_app()

    payload = {
        "locations": [
            {"id": "depot", "lat": "wrong", "lon": 80.30},
            {"id": "stop_1", "lat": 26.45, "lon": 80.35},
        ],
        "algorithm": "bidirectional_astar",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/matrix", json=payload)

    assert response.status_code == 422


def test_matrix_endpoint_rejects_empty_location_id():
    app = _create_test_app()

    payload = {
        "locations": [
            {"id": "   ", "lat": 26.44, "lon": 80.30},
            {"id": "stop_1", "lat": 26.45, "lon": 80.35},
        ],
        "algorithm": "bidirectional_astar",
        "use_cache": True,
    }

    with TestClient(app) as client:
        response = client.post("/matrix", json=payload)

    assert response.status_code == 422