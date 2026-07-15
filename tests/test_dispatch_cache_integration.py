# tests/test_dispatch_cache_integration.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.core.dispatch_cost_matrix import (
    DispatchDriver,
    DispatchOrder,
)
from app.schemas.dispatch import (
    DispatchCompareRequest,
)
from app.services.dispatch_distance_service import (
    build_dispatch_distance_lookup,
)
from app.services.dispatch_service import (
    compare_dispatch_assignments,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run async service tests with asyncio only."""

    return "asyncio"


class FakeDispatchCache:
    """
    In-memory fake cache for the legacy Phase 9.1 dispatch-distance path.

    Multiple method aliases are intentionally provided so the fake remains
    compatible with the cache adapter contract used by the current
    dispatch-distance service.
    """

    def __init__(self) -> None:
        self.store: dict[
            str,
            Any,
        ] = {}

        self.get_calls: list[
            str
        ] = []

        self.set_calls: list[
            tuple[
                str,
                Any,
                int | None,
            ]
        ] = []

    def get(
        self,
        key: str,
    ) -> Any | None:
        self.get_calls.append(
            key
        )

        return self.store.get(
            key
        )

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> bool:
        if (
            ttl_seconds is None
            and "ttl" in kwargs
        ):
            ttl_seconds = int(
                kwargs["ttl"]
            )

        self.set_calls.append(
            (
                key,
                value,
                ttl_seconds,
            )
        )

        self.store[
            key
        ] = value

        return True

    def get_json(
        self,
        key: str,
    ) -> Any | None:
        return self.get(
            key
        )

    def set_json(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> bool:
        return self.set(
            key,
            value,
            ttl_seconds,
            **kwargs,
        )

    def get_text(
        self,
        key: str,
    ) -> Any | None:
        return self.get(
            key
        )

    def set_text(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        **kwargs: Any,
    ) -> bool:
        return self.set(
            key,
            value,
            ttl_seconds,
            **kwargs,
        )


class CountingSourceDijkstraBuilder:
    """
    Deterministic injected source-Dijkstra matrix builder.

    The call counter proves that a warm cache hit avoids recomputation.
    """

    def __init__(
        self,
        *,
        matrix: Sequence[
            Sequence[
                float | None
            ]
        ],
    ) -> None:
        self.matrix = [
            list(
                row
            )
            for row
            in matrix
        ]

        self.call_count = 0

    def __call__(
        self,
        drivers: Sequence[
            DispatchDriver
        ],
        orders: Sequence[
            DispatchOrder
        ],
    ) -> list[
        list[
            float | None
        ]
    ]:
        self.call_count += 1

        assert (
            len(
                self.matrix
            )
            == len(
                drivers
            )
        )

        assert all(
            len(
                row
            )
            == len(
                orders
            )
            for row
            in self.matrix
        )

        return [
            list(
                row
            )
            for row
            in self.matrix
        ]


def _drivers() -> list[
    DispatchDriver
]:
    return [
        DispatchDriver(
            driver_id="driver_1",
            lat=26.4500,
            lon=80.3500,
            current_load=0,
            max_capacity=1,
        ),
        DispatchDriver(
            driver_id="driver_2",
            lat=26.4600,
            lon=80.3600,
            current_load=0,
            max_capacity=1,
        ),
    ]


def _orders() -> list[
    DispatchOrder
]:
    return [
        DispatchOrder(
            order_id="order_1",
            pickup_lat=26.4510,
            pickup_lon=80.3510,
        ),
        DispatchOrder(
            order_id="order_2",
            pickup_lat=26.4610,
            pickup_lon=80.3610,
        ),
    ]


def _request_payload() -> dict[
    str,
    Any,
]:
    return {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.4500,
                "lon": 80.3500,
                "current_load": 0,
                "max_capacity": 1,
            },
            {
                "driver_id": "driver_2",
                "lat": 26.4600,
                "lon": 80.3600,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4510,
                "pickup_lon": 80.3510,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4610,
                "pickup_lon": 80.3610,
            },
        ],
        "matrix_algorithm": "source_dijkstra",
        "use_cache": True,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def test_dispatch_distance_cache_miss_then_hit_for_source_dijkstra():
    cache = FakeDispatchCache()

    builder = (
        CountingSourceDijkstraBuilder(
            matrix=[
                [
                    100.0,
                    500.0,
                ],
                [
                    600.0,
                    120.0,
                ],
            ]
        )
    )

    drivers = _drivers()
    orders = _orders()

    first = (
        build_dispatch_distance_lookup(
            drivers=drivers,
            orders=orders,
            matrix_algorithm=(
                "source_dijkstra"
            ),
            source_dijkstra_matrix_builder=(
                builder
            ),
            use_cache=True,
            cache_backend=cache,
            cache_ttl_seconds=600,
        )
    )

    second = (
        build_dispatch_distance_lookup(
            drivers=drivers,
            orders=orders,
            matrix_algorithm=(
                "source_dijkstra"
            ),
            source_dijkstra_matrix_builder=(
                builder
            ),
            use_cache=True,
            cache_backend=cache,
            cache_ttl_seconds=600,
        )
    )

    assert first.cache_used is True
    assert first.cache_hit is False
    assert first.cache_key is not None

    assert second.cache_used is True
    assert second.cache_hit is True

    assert (
        second.cache_key
        == first.cache_key
    )

    # Cold request computes once.
    # Warm request must reuse cached data.
    assert builder.call_count == 1

    assert (
        first.distance_lookup(
            drivers[0],
            orders[0],
        )
        == 100.0
    )

    assert (
        second.distance_lookup(
            drivers[1],
            orders[1],
        )
        == 120.0
    )


def test_dispatch_distance_cache_disabled_skips_cache_backend():
    cache = FakeDispatchCache()

    builder = (
        CountingSourceDijkstraBuilder(
            matrix=[
                [
                    100.0,
                    500.0,
                ],
                [
                    600.0,
                    120.0,
                ],
            ]
        )
    )

    result = (
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm=(
                "source_dijkstra"
            ),
            source_dijkstra_matrix_builder=(
                builder
            ),
            use_cache=False,
            cache_backend=cache,
            cache_ttl_seconds=600,
        )
    )

    assert result.cache_used is False
    assert result.cache_hit is False
    assert result.cache_key is None

    assert builder.call_count == 1

    assert cache.get_calls == []
    assert cache.set_calls == []


def test_dispatch_distance_cache_ignores_corrupt_cached_value_and_rebuilds():
    cache = FakeDispatchCache()

    builder = (
        CountingSourceDijkstraBuilder(
            matrix=[
                [
                    100.0,
                    500.0,
                ],
                [
                    600.0,
                    120.0,
                ],
            ]
        )
    )

    drivers = _drivers()
    orders = _orders()

    # First request creates the canonical cache key and stores a valid value.
    first = (
        build_dispatch_distance_lookup(
            drivers=drivers,
            orders=orders,
            matrix_algorithm=(
                "source_dijkstra"
            ),
            source_dijkstra_matrix_builder=(
                builder
            ),
            use_cache=True,
            cache_backend=cache,
            cache_ttl_seconds=600,
        )
    )

    assert first.cache_key is not None
    assert builder.call_count == 1

    # Replace the valid value with a deliberately malformed cache payload.
    cache.store[
        first.cache_key
    ] = (
        "not-a-valid-dispatch-distance-cache-payload"
    )

    second = (
        build_dispatch_distance_lookup(
            drivers=drivers,
            orders=orders,
            matrix_algorithm=(
                "source_dijkstra"
            ),
            source_dijkstra_matrix_builder=(
                builder
            ),
            use_cache=True,
            cache_backend=cache,
            cache_ttl_seconds=600,
        )
    )

    # Corrupt cache must not be treated as a successful warm hit.
    assert second.cache_used is True
    assert second.cache_hit is False

    # Matrix must be rebuilt.
    assert builder.call_count == 2

    assert (
        second.distance_lookup(
            drivers[0],
            orders[0],
        )
        == 100.0
    )

    assert (
        second.distance_lookup(
            drivers[1],
            orders[1],
        )
        == 120.0
    )


@pytest.mark.anyio
async def test_dispatch_service_cache_miss_then_hit_for_source_dijkstra():
    cache = FakeDispatchCache()

    builder = (
        CountingSourceDijkstraBuilder(
            matrix=[
                [
                    100.0,
                    500.0,
                ],
                [
                    600.0,
                    120.0,
                ],
            ]
        )
    )

    request = DispatchCompareRequest(
        **_request_payload()
    )

    first = await compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=(
            builder
        ),
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    second = await compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=(
            builder
        ),
        cache_backend=cache,
        cache_ttl_seconds=600,
    )

    assert first.status == "ok"
    assert second.status == "ok"

    assert (
        first.phase
        == "tier3_phase10"
    )

    assert (
        second.phase
        == "tier3_phase10"
    )

    assert first.cache_used is True
    assert first.cache_hit is False
    assert first.cache_key is not None

    assert second.cache_used is True
    assert second.cache_hit is True

    assert (
        second.cache_key
        == first.cache_key
    )

    # Phase 10 service now also exposes normalized legacy cache telemetry.
    assert first.cache_status == "miss"
    assert first.cache_hits == 0
    assert first.cache_misses == 1

    assert second.cache_status == "hit"
    assert second.cache_hits == 1
    assert second.cache_misses == 0

    # This is the preserved injected-builder compatibility path, not the
    # live road-matrix dependency path.
    assert first.road_network is None
    assert second.road_network is None

    # The source-Dijkstra matrix is computed only on the cold request.
    assert builder.call_count == 1

    # Assignment output must remain stable across miss and hit.
    assert (
        first.hungarian.total_cost
        == second.hungarian.total_cost
    )

    assert (
        first.hungarian.assigned_count
        == second.hungarian.assigned_count
    )

    assert (
        first.comparison
        .hungarian_non_regression
        == second.comparison
        .hungarian_non_regression
    )


@pytest.mark.anyio
async def test_dispatch_service_cache_key_changes_when_payload_changes():
    cache = FakeDispatchCache()

    builder = (
        CountingSourceDijkstraBuilder(
            matrix=[
                [
                    100.0,
                    500.0,
                ],
                [
                    600.0,
                    120.0,
                ],
            ]
        )
    )

    first_request = (
        DispatchCompareRequest(
            **_request_payload()
        )
    )

    second_payload = (
        _request_payload()
    )

    second_payload[
        "orders"
    ][
        1
    ][
        "pickup_lat"
    ] = 26.462

    second_request = (
        DispatchCompareRequest(
            **second_payload
        )
    )

    first = await compare_dispatch_assignments(
        first_request,
        source_dijkstra_matrix_builder=(
            builder
        ),
        cache_backend=cache,
    )

    second = await compare_dispatch_assignments(
        second_request,
        source_dijkstra_matrix_builder=(
            builder
        ),
        cache_backend=cache,
    )

    assert first.cache_key is not None
    assert second.cache_key is not None

    assert (
        first.cache_key
        != second.cache_key
    )

    # Both payloads are cold because their coordinates produce different
    # cache fingerprints.
    assert first.cache_hit is False
    assert second.cache_hit is False

    assert first.cache_status == "miss"
    assert second.cache_status == "miss"

    assert builder.call_count == 2