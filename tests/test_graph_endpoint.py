# tests/test_graph_endpoints.py

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _inside_bbox_coordinate() -> tuple[float, float]:
    lat = round((settings.bbox_south + settings.bbox_north) / 2, 6)
    lon = round((settings.bbox_west + settings.bbox_east) / 2, 6)
    return lat, lon


def _outside_bbox_coordinate() -> tuple[float, float]:
    lat = round(settings.bbox_south - 1, 6)
    lon = round((settings.bbox_west + settings.bbox_east) / 2, 6)
    return lat, lon


def test_graph_stats_returns_loaded_graph_metadata():
    with TestClient(app) as client:
        response = client.get("/graph/stats")

    assert response.status_code == 200

    data = response.json()

    assert data["graph_loaded"] is True
    assert "Kanpur" in data["city"]
    assert data["nodes"] > 0
    assert data["edges"] > 0
    assert data["graph_path"].replace("\\", "/") == "data/graphs/kanpur_central.graphml"
    assert data["graph_file_size_mb"] is not None
    assert data["graph_file_size_mb"] > 0
    assert data["load_time_s"] is not None
    assert data["memory_mb"] is not None
    assert data["memory_mb"] > 0


def test_graph_validate_accepts_coordinate_inside_bbox():
    lat, lon = _inside_bbox_coordinate()

    with TestClient(app) as client:
        response = client.get(f"/graph/validate?lat={lat}&lon={lon}")

    assert response.status_code == 200

    data = response.json()

    assert data["valid"] is True
    assert data["lat"] == lat
    assert data["lon"] == lon


def test_graph_validate_rejects_coordinate_outside_bbox():
    lat, lon = _outside_bbox_coordinate()

    with TestClient(app) as client:
        response = client.get(f"/graph/validate?lat={lat}&lon={lon}")

    assert response.status_code == 422

    data = response.json()

    assert data["detail"]["error"] == "Coordinate outside loaded graph area"
    assert "allowed_bbox" in data["detail"]


def test_graph_snap_accepts_coordinate_inside_bbox():
    lat, lon = _inside_bbox_coordinate()

    with TestClient(app) as client:
        response = client.get(f"/graph/snap?lat={lat}&lon={lon}")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["message"] == "Coordinate snapped to nearest graph node."
    assert data["input"]["lat"] == lat
    assert data["input"]["lon"] == lon
    assert isinstance(data["nearest_node"], int)
    assert isinstance(data["snapped"]["lat"], float)
    assert isinstance(data["snapped"]["lon"], float)
    assert data["snap_time_ms"] >= 0
    assert data["snap_method"] == "balltree"
    assert data["snap_distance_m"] >= 0


def test_graph_snap_rejects_coordinate_outside_bbox():
    lat, lon = _outside_bbox_coordinate()

    with TestClient(app) as client:
        response = client.get(f"/graph/snap?lat={lat}&lon={lon}")

    assert response.status_code == 422

    data = response.json()

    assert data["detail"]["error"] == "Coordinate outside loaded graph area"

def test_graph_stats_includes_connectivity_metadata():
    with TestClient(app) as client:
        response = client.get("/graph/stats")

    assert response.status_code == 200

    data = response.json()

    assert "weakly_connected_components" in data
    assert "largest_component_nodes" in data
    assert "is_weakly_connected" in data
    assert data["weakly_connected_components"] >= 1
    assert data["largest_component_nodes"] > 0
    assert isinstance(data["is_weakly_connected"], bool)