# tests/test_dispatch_source_dijkstra.py

from __future__ import annotations

import pytest

from app.core.dispatch_cost_matrix import DispatchDriver, DispatchOrder
from app.schemas.dispatch import DispatchCompareRequest
from app.services.dispatch_distance_service import (
    DispatchDistanceError,
    build_dispatch_distance_lookup,
)
from app.services.dispatch_service import compare_dispatch_assignments


def _drivers() -> list[DispatchDriver]:
    return [
        DispatchDriver(
            driver_id="driver_1",
            lat=26.45,
            lon=80.35,
            current_load=0,
            max_capacity=1,
        ),
        DispatchDriver(
            driver_id="driver_2",
            lat=26.46,
            lon=80.36,
            current_load=0,
            max_capacity=1,
        ),
    ]


def _orders() -> list[DispatchOrder]:
    return [
        DispatchOrder(
            order_id="order_1",
            pickup_lat=26.451,
            pickup_lon=80.351,
        ),
        DispatchOrder(
            order_id="order_2",
            pickup_lat=26.461,
            pickup_lon=80.361,
        ),
    ]


def _source_dijkstra_builder(
    drivers: list[DispatchDriver],
    orders: list[DispatchOrder],
) -> list[list[float]]:
    assert len(drivers) == 2
    assert len(orders) == 2

    return [
        [100.0, 500.0],
        [600.0, 120.0],
    ]


def _source_dijkstra_builder_with_unreachable(
    drivers: list[DispatchDriver],
    orders: list[DispatchOrder],
) -> list[list[float | None]]:
    assert len(drivers) == 2
    assert len(orders) == 2

    return [
        [100.0, None],
        [None, 120.0],
    ]


def _request_payload(matrix_algorithm: str = "source_dijkstra") -> dict:
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
        "matrix_algorithm": matrix_algorithm,
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": True,
    }


def test_source_dijkstra_distance_lookup_requires_builder():
    with pytest.raises(DispatchDistanceError, match="source_dijkstra_matrix_builder"):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=None,
            use_cache=False,
        )


def test_source_dijkstra_distance_lookup_uses_injected_builder():
    result = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=_source_dijkstra_builder,
        use_cache=False,
    )

    assert result.matrix_algorithm == "source_dijkstra"
    assert result.cache_used is False
    assert result.cache_hit is False
    assert result.cache_key is None
    assert result.driver_ids == ["driver_1", "driver_2"]
    assert result.order_ids == ["order_1", "order_2"]
    assert result.driver_order_distance_matrix == [
        [100.0, 500.0],
        [600.0, 120.0],
    ]


def test_source_dijkstra_distance_lookup_returns_driver_order_costs():
    result = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=_source_dijkstra_builder,
        use_cache=False,
    )

    assert result.distance_lookup(_drivers()[0], _orders()[0]) == 100.0
    assert result.distance_lookup(_drivers()[0], _orders()[1]) == 500.0
    assert result.distance_lookup(_drivers()[1], _orders()[0]) == 600.0
    assert result.distance_lookup(_drivers()[1], _orders()[1]) == 120.0


def test_source_dijkstra_distance_lookup_converts_unreachable_to_large_cost():
    result = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=_source_dijkstra_builder_with_unreachable,
        use_cache=False,
    )

    assert result.driver_order_distance_matrix[0][0] == 100.0
    assert result.driver_order_distance_matrix[0][1] > 1_000_000_000
    assert result.driver_order_distance_matrix[1][0] > 1_000_000_000
    assert result.driver_order_distance_matrix[1][1] == 120.0


def test_source_dijkstra_distance_lookup_rejects_wrong_row_count():
    def bad_builder(
        drivers: list[DispatchDriver],
        orders: list[DispatchOrder],
    ) -> list[list[float]]:
        return [[100.0, 200.0]]

    with pytest.raises(DispatchDistanceError, match="row count mismatch"):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=bad_builder,
            use_cache=False,
        )


def test_source_dijkstra_distance_lookup_rejects_wrong_column_count():
    def bad_builder(
        drivers: list[DispatchDriver],
        orders: list[DispatchOrder],
    ) -> list[list[float]]:
        return [
            [100.0],
            [200.0],
        ]

    with pytest.raises(DispatchDistanceError, match="column count mismatch"):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=bad_builder,
            use_cache=False,
        )


def test_dispatch_service_source_dijkstra_works_with_injected_builder():
    request = DispatchCompareRequest(**_request_payload())

    response = compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=_source_dijkstra_builder,
        cache_backend=None,
    )

    assert response.status == "ok"
    assert response.phase == "tier3_phase9_1"
    assert response.matrix_algorithm == "source_dijkstra"
    assert response.cache_used is False
    assert response.cache_hit is False
    assert response.cache_key is None

    assert response.driver_count == 2
    assert response.order_count == 2
    assert response.available_slot_count == 2
    assert response.assigned_order_count == 2
    assert response.unassigned_order_count == 0
    assert response.unused_slot_count == 0

    assert response.hungarian.assigned_count == 2
    assert response.hungarian.total_cost == 220.0
    assert response.hungarian.assignments[0].driver_id == "driver_1"
    assert response.hungarian.assignments[0].order_id == "order_1"
    assert response.hungarian.assignments[1].driver_id == "driver_2"
    assert response.hungarian.assignments[1].order_id == "order_2"


def test_dispatch_service_source_dijkstra_keeps_hungarian_non_regression():
    request = DispatchCompareRequest(**_request_payload())

    response = compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=_source_dijkstra_builder,
        cache_backend=None,
    )

    assert response.comparison.hungarian_non_regression is True
    assert response.hungarian.total_cost <= response.greedy.total_cost


def test_dispatch_service_haversine_still_works_without_builder():
    request = DispatchCompareRequest(**_request_payload(matrix_algorithm="haversine"))

    response = compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=None,
        cache_backend=None,
    )

    assert response.status == "ok"
    assert response.matrix_algorithm == "haversine"
    assert response.assigned_order_count == 2
    assert response.hungarian.total_cost >= 0