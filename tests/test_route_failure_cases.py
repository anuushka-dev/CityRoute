# tests/test_route_failure_cases.py

import networkx as nx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.routing_service import compute_route


def _valid_route_params() -> dict:
    return {
        "start_lat": 26.44,
        "start_lon": 80.30,
        "end_lat": 26.45,
        "end_lon": 80.35,
    }


def test_route_missing_all_query_params_returns_422():
    with TestClient(app) as client:
        response = client.get("/route")

    assert response.status_code == 422


def test_route_rejects_non_numeric_latitude():
    params = _valid_route_params()
    params["start_lat"] = "not-a-number"

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422


def test_route_rejects_invalid_latitude_above_90():
    params = _valid_route_params()
    params["start_lat"] = 91

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Invalid latitude"


def test_route_rejects_invalid_latitude_below_minus_90():
    params = _valid_route_params()
    params["start_lat"] = -91

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Invalid latitude"


def test_route_rejects_invalid_longitude_above_180():
    params = _valid_route_params()
    params["start_lon"] = 181

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Invalid longitude"


def test_route_rejects_invalid_longitude_below_minus_180():
    params = _valid_route_params()
    params["start_lon"] = -181

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Invalid longitude"


def test_route_rejects_start_coordinate_outside_bbox():
    params = _valid_route_params()
    params["start_lat"] = float(settings.bbox_south) - 1

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Coordinate outside loaded graph area"


def test_route_rejects_end_coordinate_outside_bbox():
    params = _valid_route_params()
    params["end_lon"] = float(settings.bbox_east) + 1

    with TestClient(app) as client:
        response = client.get("/route", params=params)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Coordinate outside loaded graph area"


def test_compute_route_returns_503_when_graph_missing():
    with pytest.raises(HTTPException) as exc_info:
        compute_route(
            graph=None,
            snap_index=None,
            start_lat=26.44,
            start_lon=80.30,
            end_lat=26.45,
            end_lon=80.35,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "Graph not loaded"


def test_route_returns_404_when_astar_reports_no_path(monkeypatch):
    def fake_astar_no_path(graph, start_node, end_node):
        raise nx.NetworkXNoPath(f"No path found between {start_node} and {end_node}")

    monkeypatch.setattr(
        "app.services.routing_service.astar_shortest_path",
        fake_astar_no_path,
    )

    with TestClient(app) as client:
        response = client.get("/route", params=_valid_route_params())

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "No path found"
