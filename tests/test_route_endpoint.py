# tests/test_route_endpoint.py

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _inside_start_coordinate() -> tuple[float, float]:
    lat = (float(settings.bbox_south) + float(settings.bbox_north)) / 2
    lon = (float(settings.bbox_west) + float(settings.bbox_east)) / 2
    return lat, lon


def _inside_end_coordinate() -> tuple[float, float]:
    lat = float(settings.bbox_north) - 0.01
    lon = float(settings.bbox_east) - 0.01
    return lat, lon


def test_route_returns_astar_result_for_valid_coordinates():
    start_lat, start_lon = _inside_start_coordinate()
    end_lat, end_lon = _inside_end_coordinate()

    with TestClient(app) as client:
        response = client.get(
            "/route",
            params={
                "start_lat": start_lat,
                "start_lon": start_lon,
                "end_lat": end_lat,
                "end_lon": end_lon,
            },
        )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["algorithm"] == "astar"

    assert data["distance_m"] >= 0
    assert data["distance_km"] >= 0
    assert data["eta_seconds"] >= 0
    assert data["eta_minutes"] >= 0

    assert data["path_node_count"] >= 1
    assert data["nodes_expanded"] >= 0
    assert data["route_time_ms"] >= 0
    assert data["total_time_ms"] >= data["route_time_ms"]

    assert isinstance(data["geometry"], list)
    assert len(data["geometry"]) == data["path_node_count"]

    first_point = data["geometry"][0]
    assert "lat" in first_point
    assert "lon" in first_point

    assert data["start"]["snap_method"] == "balltree"
    assert data["end"]["snap_method"] == "balltree"


def test_route_rejects_start_coordinate_outside_bbox():
    end_lat, end_lon = _inside_end_coordinate()

    with TestClient(app) as client:
        response = client.get(
            "/route",
            params={
                "start_lat": float(settings.bbox_south) - 1,
                "start_lon": float(settings.bbox_west),
                "end_lat": end_lat,
                "end_lon": end_lon,
            },
        )

    assert response.status_code == 422

    data = response.json()
    assert data["detail"]["error"] == "Coordinate outside loaded graph area"


def test_route_rejects_end_coordinate_outside_bbox():
    start_lat, start_lon = _inside_start_coordinate()

    with TestClient(app) as client:
        response = client.get(
            "/route",
            params={
                "start_lat": start_lat,
                "start_lon": start_lon,
                "end_lat": float(settings.bbox_north) + 1,
                "end_lon": float(settings.bbox_east),
            },
        )

    assert response.status_code == 422

    data = response.json()
    assert data["detail"]["error"] == "Coordinate outside loaded graph area"