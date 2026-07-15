# tests/test_dispatch_source_dijkstra.py

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.core.dispatch_cost_matrix import (
    DispatchDriver,
    DispatchOrder,
)
from app.schemas.dispatch import (
    DispatchCompareRequest,
)
from app.services.dispatch_distance_service import (
    DispatchDistanceError,
    build_dispatch_distance_lookup,
)
from app.services.dispatch_service import (
    compare_dispatch_assignments,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests with asyncio only."""

    return "asyncio"


def _drivers() -> list[DispatchDriver]:
    return [
        DispatchDriver(
            driver_id="driver_1",
            lat=26.4499,
            lon=80.3319,
            current_load=0,
            max_capacity=1,
        ),
        DispatchDriver(
            driver_id="driver_2",
            lat=26.4600,
            lon=80.3500,
            current_load=0,
            max_capacity=1,
        ),
    ]


def _orders() -> list[DispatchOrder]:
    return [
        DispatchOrder(
            order_id="order_1",
            pickup_lat=26.4510,
            pickup_lon=80.3330,
        ),
        DispatchOrder(
            order_id="order_2",
            pickup_lat=26.4610,
            pickup_lon=80.3510,
        ),
    ]


def _request_payload(
    *,
    matrix_algorithm: str = "source_dijkstra",
) -> dict:
    return {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.4499,
                "lon": 80.3319,
                "current_load": 0,
                "max_capacity": 1,
            },
            {
                "driver_id": "driver_2",
                "lat": 26.4600,
                "lon": 80.3500,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4510,
                "pickup_lon": 80.3330,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4610,
                "pickup_lon": 80.3510,
            },
        ],
        "matrix_algorithm": matrix_algorithm,
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def _source_dijkstra_builder(
    drivers: Sequence[DispatchDriver],
    orders: Sequence[DispatchOrder],
) -> list[list[float]]:
    assert len(drivers) == 2
    assert len(orders) == 2

    return [
        [
            100.0,
            500.0,
        ],
        [
            600.0,
            120.0,
        ],
    ]


def test_source_dijkstra_distance_lookup_requires_builder():
    with pytest.raises(
        DispatchDistanceError
    ):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=None,
            use_cache=False,
            cache_backend=None,
        )


def test_source_dijkstra_distance_lookup_uses_injected_builder():
    call_count = 0

    def builder(
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float]]:
        nonlocal call_count

        call_count += 1

        assert len(drivers) == 2
        assert len(orders) == 2

        return [
            [
                100.0,
                500.0,
            ],
            [
                600.0,
                120.0,
            ],
        ]

    result = build_dispatch_distance_lookup(
        drivers=_drivers(),
        orders=_orders(),
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=False,
        cache_backend=None,
    )

    assert call_count == 1
    assert result.cache_used is False
    assert result.cache_hit is False


def test_source_dijkstra_distance_lookup_returns_driver_order_costs():
    drivers = _drivers()
    orders = _orders()

    result = build_dispatch_distance_lookup(
        drivers=drivers,
        orders=orders,
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=(
            _source_dijkstra_builder
        ),
        use_cache=False,
        cache_backend=None,
    )

    assert (
        result.distance_lookup(
            drivers[0],
            orders[0],
        )
        == 100.0
    )

    assert (
        result.distance_lookup(
            drivers[0],
            orders[1],
        )
        == 500.0
    )

    assert (
        result.distance_lookup(
            drivers[1],
            orders[0],
        )
        == 600.0
    )

    assert (
        result.distance_lookup(
            drivers[1],
            orders[1],
        )
        == 120.0
    )


def test_source_dijkstra_distance_lookup_converts_unreachable_to_large_cost():
    drivers = _drivers()
    orders = _orders()

    def builder(
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float | None]]:
        assert len(drivers) == 2
        assert len(orders) == 2

        return [
            [
                100.0,
                None,
            ],
            [
                600.0,
                120.0,
            ],
        ]

    result = build_dispatch_distance_lookup(
        drivers=drivers,
        orders=orders,
        matrix_algorithm="source_dijkstra",
        source_dijkstra_matrix_builder=builder,
        use_cache=False,
        cache_backend=None,
    )

    unreachable_cost = result.distance_lookup(
        drivers[0],
        orders[1],
    )

    assert unreachable_cost > 0.0

    assert unreachable_cost > result.distance_lookup(
        drivers[0],
        orders[0],
    )


def test_source_dijkstra_distance_lookup_rejects_wrong_row_count():
    def builder(
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float]]:
        del drivers
        del orders

        return [
            [
                100.0,
                500.0,
            ]
        ]

    with pytest.raises(
        DispatchDistanceError
    ):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=builder,
            use_cache=False,
            cache_backend=None,
        )


def test_source_dijkstra_distance_lookup_rejects_wrong_column_count():
    def builder(
        drivers: Sequence[DispatchDriver],
        orders: Sequence[DispatchOrder],
    ) -> list[list[float]]:
        del drivers
        del orders

        return [
            [
                100.0,
            ],
            [
                600.0,
            ],
        ]

    with pytest.raises(
        DispatchDistanceError
    ):
        build_dispatch_distance_lookup(
            drivers=_drivers(),
            orders=_orders(),
            matrix_algorithm="source_dijkstra",
            source_dijkstra_matrix_builder=builder,
            use_cache=False,
            cache_backend=None,
        )


@pytest.mark.anyio
async def test_dispatch_service_source_dijkstra_works_with_injected_builder():
    request = DispatchCompareRequest(
        **_request_payload()
    )

    response = await compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=(
            _source_dijkstra_builder
        ),
        cache_backend=None,
    )

    assert response.status == "ok"

    assert (
        response.phase
        == "tier3_phase10"
    )

    assert (
        response.matrix_algorithm
        == "source_dijkstra"
    )

    assert response.driver_count == 2
    assert response.order_count == 2
    assert response.assigned_order_count == 2

    assert (
        response.hungarian.assigned_count
        == 2
    )

    # This test exercises the legacy injected-builder compatibility path,
    # not the new live Phase 10 road-matrix dependency path.
    assert response.road_network is None


@pytest.mark.anyio
async def test_dispatch_service_source_dijkstra_keeps_hungarian_non_regression():
    request = DispatchCompareRequest(
        **_request_payload()
    )

    response = await compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=(
            _source_dijkstra_builder
        ),
        cache_backend=None,
    )

    assert (
        response.comparison
        .hungarian_non_regression
        is True
    )

    assert (
        response.hungarian.assigned_count
        >= response.greedy.assigned_count
    )


@pytest.mark.anyio
async def test_dispatch_service_haversine_still_works_without_builder():
    request = DispatchCompareRequest(
        **_request_payload(
            matrix_algorithm="haversine"
        )
    )

    response = await compare_dispatch_assignments(
        request,
        source_dijkstra_matrix_builder=None,
        cache_backend=None,
    )

    assert response.status == "ok"

    assert (
        response.phase
        == "tier3_phase10"
    )

    assert (
        response.matrix_algorithm
        == "haversine"
    )

    assert response.road_network is None

    assert (
        response.hungarian.assigned_count
        == 2
    )