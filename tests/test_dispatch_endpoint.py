# tests/test_dispatch_endpoint.py

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _valid_payload() -> dict:
    return {
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
        "return_cost_breakdown": True,
    }


def test_dispatch_compare_route_is_registered_in_openapi():
    response = client.get("/openapi.json")

    assert response.status_code == 200

    paths = response.json()["paths"]

    assert "/dispatch/compare" in paths
    assert "post" in paths["/dispatch/compare"]


def test_root_lists_dispatch_compare_endpoint():
    response = client.get("/")

    assert response.status_code == 200

    body = response.json()

    assert body["dispatch_compare"] == "/dispatch/compare"
    assert (
        body["phase"]
        == "Tier 3 Phase 10 - Real Road-Network Dispatch Integration"
    )
    assert body["phase_code"] == "tier3_phase10"
    assert "haversine" in body["dispatch_matrix_algorithms"]
    assert "source_dijkstra" in body["dispatch_matrix_algorithms"]


def test_dispatch_compare_valid_payload_returns_ok():
    response = client.post("/dispatch/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["phase"] == "tier3_phase10"
    assert body["driver_count"] == 2
    assert body["order_count"] == 2
    assert body["available_slot_count"] == 2
    assert body["assigned_order_count"] == 2
    assert body["unassigned_order_count"] == 0
    assert body["unused_slot_count"] == 0
    assert body["matrix_algorithm"] == "haversine"
    assert body["cache_used"] is False
    assert body["cache_hit"] is False
    assert body["cache_key"] is None
    assert body["road_network"] is None


def test_dispatch_compare_returns_greedy_and_hungarian_results():
    response = client.post("/dispatch/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["greedy"]["algorithm"] == "greedy_dispatch"
    assert body["hungarian"]["algorithm"] == "hungarian"

    assert body["greedy"]["assigned_count"] == 2
    assert body["hungarian"]["assigned_count"] == 2

    assert len(body["greedy"]["assignments"]) == 2
    assert len(body["hungarian"]["assignments"]) == 2


def test_dispatch_compare_hungarian_is_not_worse_than_greedy():
    response = client.post("/dispatch/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["comparison"]["hungarian_non_regression"] is True
    assert body["hungarian"]["total_cost"] <= body["greedy"]["total_cost"]


def test_dispatch_compare_assigns_each_order_at_most_once():
    response = client.post("/dispatch/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assigned_order_ids = [
        assignment["order_id"]
        for assignment in body["hungarian"]["assignments"]
    ]

    assert len(assigned_order_ids) == len(set(assigned_order_ids))


def test_dispatch_compare_returns_cost_breakdown_when_requested():
    payload = _valid_payload()
    payload["return_cost_breakdown"] = True

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200

    body = response.json()

    assert len(body["cost_breakdown"]) == 4

    first = body["cost_breakdown"][0]

    assert first["driver_id"] == "driver_1"
    assert first["order_id"] == "order_1"
    assert first["row_index"] == 0
    assert first["col_index"] == 0
    assert first["distance_m"] >= 0
    assert first["total_cost"] >= first["distance_m"]
    assert first["allowed"] is True


def test_dispatch_compare_omits_cost_breakdown_by_default():
    payload = _valid_payload()
    payload["return_cost_breakdown"] = False

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200
    assert response.json()["cost_breakdown"] == []


def test_dispatch_compare_returns_fairness_metrics():
    response = client.post("/dispatch/compare", json=_valid_payload())

    assert response.status_code == 200

    body = response.json()

    assert body["greedy_fairness"]["driver_count"] == 2
    assert body["hungarian_fairness"]["driver_count"] == 2
    assert body["hungarian_fairness"]["total_assigned_orders"] == 2
    assert body["hungarian_fairness"]["total_available_slots"] == 2
    assert len(body["hungarian_fairness"]["driver_metrics"]) == 2
    assert 0 <= body["hungarian_fairness"]["fairness_score"] <= 100


def test_dispatch_compare_more_orders_than_capacity_returns_unassigned_orders():
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
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.452,
                "pickup_lon": 80.352,
            },
            {
                "order_id": "order_3",
                "pickup_lat": 26.453,
                "pickup_lon": 80.353,
            },
        ],
        "matrix_algorithm": "haversine",
    }

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200

    body = response.json()

    assert body["assigned_order_count"] == 1
    assert body["unassigned_order_count"] == 2
    assert len(body["hungarian"]["unassigned_order_ids"]) == 2


def test_dispatch_compare_extra_capacity_returns_unused_slots():
    payload = {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.45,
                "lon": 80.35,
                "current_load": 0,
                "max_capacity": 3,
            }
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.451,
                "pickup_lon": 80.351,
            }
        ],
        "matrix_algorithm": "haversine",
    }

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200

    body = response.json()

    assert body["assigned_order_count"] == 1
    assert body["unused_slot_count"] == 2
    assert len(body["hungarian"]["unassigned_driver_slot_rows"]) == 2


def test_dispatch_compare_source_dijkstra_uses_phase10_live_road_matrix():
    payload = _valid_payload()
    payload["matrix_algorithm"] = "source_dijkstra"
    payload["use_cache"] = False

    # Phase 10 road-network dependencies are initialized during app lifespan.
    with TestClient(app) as lifespan_client:
        response = lifespan_client.post("/dispatch/compare", json=payload)

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "ok"
    assert body["phase"] == "tier3_phase10"
    assert body["matrix_algorithm"] == "source_dijkstra"
    assert body["driver_count"] == 2
    assert body["order_count"] == 2
    assert body["assigned_order_count"] == 2
    assert body["unassigned_order_count"] == 0
    assert body["cache_used"] is False
    assert body["cache_hit"] is False

    road_network = body["road_network"]

    assert road_network is not None
    assert road_network["pair_count"] == 4
    assert (
        road_network["reachable_pair_count"]
        + road_network["unreachable_pair_count"]
        == 4
    )
    assert road_network["source_search_count"] >= 1

    assert body["comparison"]["hungarian_non_regression"] is True


def test_dispatch_compare_rejects_duplicate_driver_ids_with_422():
    payload = _valid_payload()
    payload["drivers"][1]["driver_id"] = "driver_1"

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert any(
        "driver_id values must be unique" in error.get("msg", "")
        for error in detail
    )


def test_dispatch_compare_rejects_duplicate_order_ids_with_422():
    payload = _valid_payload()
    payload["orders"][1]["order_id"] = "order_1"

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert any(
        "order_id values must be unique" in error.get("msg", "")
        for error in detail
    )


def test_dispatch_compare_rejects_all_drivers_full():
    payload = _valid_payload()
    payload["drivers"] = [
        {
            "driver_id": "driver_1",
            "lat": 26.45,
            "lon": 80.35,
            "current_load": 1,
            "max_capacity": 1,
        }
    ]

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 400
    assert "available capacity" in response.json()["detail"]


def test_dispatch_compare_rejects_invalid_driver_latitude_with_422():
    payload = _valid_payload()
    payload["drivers"][0]["lat"] = 91.0

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422


def test_dispatch_compare_rejects_invalid_order_longitude_with_422():
    payload = _valid_payload()
    payload["orders"][0]["pickup_lon"] = 181.0

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422


def test_dispatch_compare_rejects_missing_drivers_with_422():
    payload = _valid_payload()
    payload["drivers"] = []

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422


def test_dispatch_compare_rejects_missing_orders_with_422():
    payload = _valid_payload()
    payload["orders"] = []

    response = client.post("/dispatch/compare", json=payload)

    assert response.status_code == 422