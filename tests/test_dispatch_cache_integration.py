# tests/test_dispatch_cache_integration.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.core.dispatch_cost_matrix import DispatchDriver, DispatchOrder
from app.schemas.dispatch import DispatchCompareRequest
from app.services.dispatch_distance_service import build_dispatch_distance_lookup
from app.services.dispatch_service import compare_dispatch_assignments


class FakeDispatchCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.get_count = 0
        self.set_count = 0
        self.last_get_key: str | None = None
        self.last_set_key: str | None = None
        self.last_ttl_seconds: int | None = None

    def get(self, key: str) -> Any:
        self.get_count += 1
        self.last_get_key = key
        return self.store.get(key)

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        self.set_count += 1
        self.last_set_key = key
        self.last_ttl_seconds = ttl_seconds
        self.store[key] = value


class CountingSourceDijkstraBuilder:
    def __init__(self, matrix: list[list[float]]) -> None:
        self.matrix = matrix
        self.call_count = 0

    def __call__(
        self,
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float]]:
        self.call_count += 1

        assert len(drivers) == len(self.matrix)
        assert len(orders) == len(self.matrix[0])

        return self.matrix


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


def _request_payload() -> dict:
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
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": True,
    }


def _assignment_pairs(response) -> list[tuple[str, str, float]]:
    return [
        (
            assignment.driver_id,
            assignment.order_id,
            assignment.cost,
        )
        for assignment in response.hungarian.assignments
    ]


def test_dispatch_distance_cache_miss_then_hit_for_source_dijkstra():
    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(
        matrix=[
            [100.0, 500.0],
            [600.0, 120.0],
        ]
    )

    first = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=True,
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    assert first.cache_used is True
    assert first.cache_hit is False
    assert first.cache_key is not None
    assert first.cache_key.startswith("dispatch:distance")
    assert first.driver_order_distance_matrix == [
        [100.0, 500.0],
        [600.0, 120.0],
    ]

    assert builder.call_count == 1
    assert cache.get_count == 1
    assert cache.set_count == 1
    assert cache.last_ttl_seconds == 600

    second = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=True,
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    assert second.cache_used is True
    assert second.cache_hit is True
    assert second.cache_key == first.cache_key
    assert second.driver_order_distance_matrix == first.driver_order_distance_matrix

    assert builder.call_count == 1
    assert cache.get_count == 2
    assert cache.set_count == 1


def test_dispatch_distance_cache_disabled_skips_cache_backend():
    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(
        matrix=[
            [100.0, 500.0],
            [600.0, 120.0],
        ]
    )

    first = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=False,
        cache_backend=cache,
    )

    second = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=False,
        cache_backend=cache,
    )

    assert first.cache_used is False
    assert first.cache_hit is False
    assert first.cache_key is None

    assert second.cache_used is False
    assert second.cache_hit is False
    assert second.cache_key is None

    assert builder.call_count == 2
    assert cache.get_count == 0
    assert cache.set_count == 0
    assert cache.store == {}


def test_dispatch_distance_cache_ignores_corrupt_cached_value_and_rebuilds():
    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(
        matrix=[
            [100.0, 500.0],
            [600.0, 120.0],
        ]
    )

    first = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=True,
        cache_backend=cache,
    )

    assert first.cache_key is not None

    cache.store[first.cache_key] = "not-json"

    second = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=True,
        cache_backend=cache,
    )

    assert second.cache_used is True
    assert second.cache_hit is False
    assert second.driver_order_distance_matrix == [
        [100.0, 500.0],
        [600.0, 120.0],
    ]

    assert builder.call_count == 2
    assert cache.set_count == 2


def test_dispatch_service_cache_miss_then_hit_for_source_dijkstra():
    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(
        matrix=[
            [100.0, 500.0],
            [600.0, 120.0],
        ]
    )

    request = DispatchCompareRequest(**_request_payload())

    first = compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=builder,
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    second = compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=builder,
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    assert first.status == "ok"
    assert first.phase == "tier3_phase9_1"
    assert first.matrix_algorithm == "source_dijkstra"
    assert first.cache_used is True
    assert first.cache_hit is False
    assert first.cache_key is not None

    assert second.status == "ok"
    assert second.phase == "tier3_phase9_1"
    assert second.matrix_algorithm == "source_dijkstra"
    assert second.cache_used is True
    assert second.cache_hit is True
    assert second.cache_key == first.cache_key

    assert builder.call_count == 1
    assert cache.get_count == 2
    assert cache.set_count == 1

    assert first.hungarian.total_cost == 220.0
    assert second.hungarian.total_cost == 220.0
    assert _assignment_pairs(first) == _assignment_pairs(second)


def test_dispatch_service_cache_key_changes_when_payload_changes():
    cache = FakeDispatchCache()
    builder = CountingSourceDijkstraBuilder(
        matrix=[
            [100.0, 500.0],
            [600.0, 120.0],
        ]
    )

    first_request = DispatchCompareRequest(**_request_payload())

    second_payload = _request_payload()
    second_payload["orders"][1]["pickup_lat"] = 26.462
    second_request = DispatchCompareRequest(**second_payload)

    first = compare_dispatch_assignments(
        first_request,
        source_dijkstra_matrix_builder=builder,
        cache_backend=cache,
    )

    second = compare_dispatch_assignments(
        second_request,
        source_dijkstra_matrix_builder=builder,
        cache_backend=cache,
    )

    assert first.cache_key is not None
    assert second.cache_key is not None
    assert first.cache_key != second.cache_key

    assert first.cache_hit is False
    assert second.cache_hit is False
    assert builder.call_count == 2
    assert cache.set_count == 2