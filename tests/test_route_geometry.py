# tests/test_route_geometry.py

from fastapi.testclient import TestClient

from app.main import app


def _rounded_point(lat: float, lon: float) -> tuple[float, float]:
    return round(float(lat), 7), round(float(lon), 7)


def test_route_geometry_points_are_graph_node_coordinates():
    with TestClient(app) as client:
        response = client.get(
            "/route",
            params={
                "start_lat": 26.44,
                "start_lon": 80.30,
                "end_lat": 26.45,
                "end_lon": 80.35,
            },
        )

        assert response.status_code == 200

        data = response.json()
        graph = client.app.state.graph

        graph_points = {
            _rounded_point(node_data["y"], node_data["x"])
            for _, node_data in graph.nodes(data=True)
        }

    assert len(data["geometry"]) == data["path_node_count"]
    assert len(data["geometry"]) > 1

    for point in data["geometry"]:
        geometry_point = _rounded_point(point["lat"], point["lon"])
        assert geometry_point in graph_points


def test_route_geometry_starts_and_ends_at_snapped_nodes():
    with TestClient(app) as client:
        response = client.get(
            "/route",
            params={
                "start_lat": 26.44,
                "start_lon": 80.30,
                "end_lat": 26.45,
                "end_lon": 80.35,
            },
        )

    assert response.status_code == 200

    data = response.json()
    geometry = data["geometry"]

    first_geometry_point = _rounded_point(geometry[0]["lat"], geometry[0]["lon"])
    start_snapped_point = _rounded_point(
        data["start"]["snapped"]["lat"],
        data["start"]["snapped"]["lon"],
    )

    last_geometry_point = _rounded_point(geometry[-1]["lat"], geometry[-1]["lon"])
    end_snapped_point = _rounded_point(
        data["end"]["snapped"]["lat"],
        data["end"]["snapped"]["lon"],
    )

    assert first_geometry_point == start_snapped_point
    assert last_geometry_point == end_snapped_point
