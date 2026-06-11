# tests/test_route_compare_endpoint.py

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app


VALID_ROUTE_PARAMS = {
    "start_lat": 26.44,
    "start_lon": 80.30,
    "end_lat": 26.45,
    "end_lon": 80.35,
}


def test_route_compare_returns_astar_and_bidirectional_sections() -> None:
    with TestClient(app) as client:
        response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert "start" in data
    assert "end" in data
    assert "astar" in data
    assert "bidirectional_astar" in data
    assert "comparison" in data

    assert data["astar"]["algorithm"] == "astar"
    assert data["bidirectional_astar"]["algorithm"] == "bidirectional_astar"


def test_route_compare_uses_same_snapped_nodes_and_balltree_method() -> None:
    with TestClient(app) as client:
        response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

    assert response.status_code == 200

    data = response.json()

    assert data["start"]["snapped_node"] == 5317312245
    assert data["end"]["snapped_node"] == 6288159135
    assert data["start"]["snap_method"] == "balltree"
    assert data["end"]["snap_method"] == "balltree"


def test_route_compare_distances_match_between_algorithms() -> None:
    with TestClient(app) as client:
        response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

    assert response.status_code == 200

    data = response.json()

    astar = data["astar"]
    bidirectional = data["bidirectional_astar"]
    comparison = data["comparison"]

    assert astar["distance_m"] == bidirectional["distance_m"]
    assert comparison["same_distance"] is True
    assert comparison["distance_delta_m"] <= 0.001


def test_route_compare_returns_bidirectional_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

    assert response.status_code == 200

    data = response.json()
    bidirectional = data["bidirectional_astar"]
    comparison = data["comparison"]

    assert bidirectional["path_node_count"] >= 1
    assert bidirectional["nodes_expanded"] >= 0
    assert bidirectional["forward_nodes_expanded"] >= 0
    assert bidirectional["backward_nodes_expanded"] >= 0
    assert bidirectional["nodes_expanded"] == (
        bidirectional["forward_nodes_expanded"]
        + bidirectional["backward_nodes_expanded"]
    )
    assert bidirectional["route_time_ms"] >= 0
    assert bidirectional["meeting_node"] is not None
    assert isinstance(bidirectional["geometry"], list)
    assert len(bidirectional["geometry"]) == bidirectional["path_node_count"]

    assert "astar_route_time_ms" in comparison
    assert "bidirectional_route_time_ms" in comparison
    assert "nodes_expanded_delta" in comparison
    assert "nodes_expanded_reduction_pct" in comparison
    assert "route_time_reduction_pct" in comparison


def test_route_compare_rejects_missing_query_params() -> None:
    with TestClient(app) as client:
        response = client.get("/route/compare")

    assert response.status_code == 422


def test_route_compare_rejects_invalid_latitude() -> None:
    params = {
        "start_lat": 91.0,
        "start_lon": 80.30,
        "end_lat": 26.45,
        "end_lon": 80.35,
    }

    with TestClient(app) as client:
        response = client.get("/route/compare", params=params)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["error"] == "Invalid latitude"


def test_route_compare_rejects_invalid_longitude() -> None:
    params = {
        "start_lat": 26.44,
        "start_lon": 181.0,
        "end_lat": 26.45,
        "end_lon": 80.35,
    }

    with TestClient(app) as client:
        response = client.get("/route/compare", params=params)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["error"] == "Invalid longitude"


def test_route_compare_rejects_start_coordinate_outside_bbox() -> None:
    params = {
        "start_lat": 26.10,
        "start_lon": 80.30,
        "end_lat": 26.45,
        "end_lon": 80.35,
    }

    with TestClient(app) as client:
        response = client.get("/route/compare", params=params)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["error"] == "Coordinate outside loaded graph area"


def test_route_compare_rejects_end_coordinate_outside_bbox() -> None:
    params = {
        "start_lat": 26.44,
        "start_lon": 80.30,
        "end_lat": 26.90,
        "end_lon": 80.35,
    }

    with TestClient(app) as client:
        response = client.get("/route/compare", params=params)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["error"] == "Coordinate outside loaded graph area"


def test_route_compare_returns_503_when_graph_missing() -> None:
    with TestClient(app) as client:
        original_graph = getattr(client.app.state, "graph", None)

        try:
            client.app.state.graph = None

            response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

        finally:
            client.app.state.graph = original_graph

    assert response.status_code == 503

    detail = response.json()["detail"]

    assert detail["error"] == "Graph not loaded"


def test_route_compare_returns_404_when_compare_service_reports_no_path(monkeypatch) -> None:
    def fake_compare_routes(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "No path found",
                "message": "No path found between test nodes",
                "start_node": 1,
                "end_node": 2,
            },
        )

    monkeypatch.setattr("app.api.route.compare_routes", fake_compare_routes)

    with TestClient(app) as client:
        response = client.get("/route/compare", params=VALID_ROUTE_PARAMS)

    assert response.status_code == 404

    detail = response.json()["detail"]

    assert detail["error"] == "No path found"
    assert detail["start_node"] == 1
    assert detail["end_node"] == 2