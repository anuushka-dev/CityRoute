# tests/test_phase91_integration_routes.py

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


REQUIRED_ENDPOINTS = {
    "/health",
    "/graph/stats",
    "/graph/validate",
    "/graph/snap",
    "/route",
    "/route/compare",
    "/matrix",
    "/vrp/greedy",
    "/vrp/compare",
    "/vrp/compare/advanced",
    "/dispatch/compare",
}


def test_phase91_required_routes_are_registered_in_openapi():
    response = client.get("/openapi.json")

    assert response.status_code == 200

    paths = set(response.json()["paths"])

    missing_paths = REQUIRED_ENDPOINTS - paths

    assert missing_paths == set()


def test_phase91_root_lists_core_phase_links():
    response = client.get("/")

    assert response.status_code == 200

    body = response.json()

    assert body["health"] == "/health"
    assert body["graph_stats"] == "/graph/stats"
    assert body["route"] == "/route"
    assert body["route_compare"] == "/route/compare"
    assert body["matrix"] == "/matrix"
    assert body["vrp_greedy"] == "/vrp/greedy"
    assert body["vrp_compare"] == "/vrp/compare"
    assert body["vrp_advanced_compare"] == "/vrp/compare/advanced"
    assert body["dispatch_compare"] == "/dispatch/compare"


def test_phase91_health_endpoint_still_works():
    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert "graph_loaded" in body


def test_phase91_graph_stats_endpoint_still_works():
    response = client.get("/graph/stats")

    assert response.status_code in {200, 503}

    body = response.json()

    if response.status_code == 200:
        assert "graph_loaded" in body

        if body["graph_loaded"] is True:
            assert body["nodes"] > 0
            assert body["edges"] > 0
        else:
            assert body["graph_loaded"] is False
    else:
        assert "detail" in body


def test_phase91_dispatch_endpoint_still_works_with_haversine():
    payload = {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.45,
                "lon": 80.35,
                "current_load": 0,
                "max_capacity": 1,
            },
            {
                "driver_id": "driver_2",
                "lat": 26.46,
                "lon": 80.36,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.451,
                "pickup_lon": 80.351,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.461,
                "pickup_lon": 80.361,
            },
        ],
        "matrix_algorithm": "haversine",
        "use_cache": True,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["phase"] in {"tier3_phase9", "tier3_phase9_1"}
    assert body["matrix_algorithm"] == "haversine"
    assert body["assigned_order_count"] == 2
    assert body["unassigned_order_count"] == 0
    assert body["comparison"]["hungarian_non_regression"] is True


def test_phase91_dispatch_source_dijkstra_api_requires_builder_until_wired():
    payload = {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.45,
                "lon": 80.35,
                "current_load": 0,
                "max_capacity": 1,
            }
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.451,
                "pickup_lon": 80.351,
            }
        ],
        "matrix_algorithm": "source_dijkstra",
        "use_cache": False,
    }

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 400

    body = response.json()

    assert "source_dijkstra" in body["detail"]
    assert "source_dijkstra_matrix_builder" in body["detail"]