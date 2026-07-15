# tests/test_dispatch_unreachable_pairs.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.core.dispatch_cost_matrix import (
    DispatchDriver,
    DispatchOrder,
    build_dispatch_cost_matrix,
)
from app.core.greedy_dispatch import (
    solve_greedy_dispatch,
)
from app.core.hungarian import (
    solve_hungarian,
)
from app.schemas.dispatch import (
    DispatchCompareRequest,
)
from app.services.dispatch_road_matrix_service import (
    DispatchRoadMatrixDependencies,
)
from app.services.dispatch_service import (
    compare_dispatch_assignments,
)


@pytest.fixture
def anyio_backend() -> str:
    """Run asynchronous tests with asyncio only."""

    return "asyncio"


# ---------------------------------------------------------------------------
# Core cost-matrix reachability tests
# ---------------------------------------------------------------------------


def test_dispatch_cost_matrix_expands_driver_reachability_across_capacity_slots():
    drivers = [
        DispatchDriver(
            driver_id="driver_1",
            lat=26.45,
            lon=80.35,
            current_load=0,
            max_capacity=2,
        ),
        DispatchDriver(
            driver_id="driver_2",
            lat=26.46,
            lon=80.36,
            current_load=0,
            max_capacity=1,
        ),
    ]

    orders = [
        DispatchOrder(
            order_id="order_1",
            pickup_lat=26.47,
            pickup_lon=80.37,
        ),
        DispatchOrder(
            order_id="order_2",
            pickup_lat=26.48,
            pickup_lon=80.38,
        ),
    ]

    distances = {
        (
            "driver_1",
            "order_1",
        ): 100.0,
        (
            "driver_1",
            "order_2",
        ): 1_000_000_000.0,
        (
            "driver_2",
            "order_1",
        ): 1_000_000_000.0,
        (
            "driver_2",
            "order_2",
        ): 200.0,
    }

    reachability = {
        (
            "driver_1",
            "order_1",
        ): True,
        (
            "driver_1",
            "order_2",
        ): False,
        (
            "driver_2",
            "order_1",
        ): False,
        (
            "driver_2",
            "order_2",
        ): True,
    }

    def distance_lookup(
        driver: DispatchDriver,
        order: DispatchOrder,
    ) -> float:
        return distances[
            (
                driver.driver_id,
                order.order_id,
            )
        ]

    def allowed_lookup(
        driver: DispatchDriver,
        order: DispatchOrder,
    ) -> bool:
        return reachability[
            (
                driver.driver_id,
                order.order_id,
            )
        ]

    result = build_dispatch_cost_matrix(
        drivers=drivers,
        orders=orders,
        distance_lookup=distance_lookup,
        allowed_lookup=allowed_lookup,
    )

    # driver_1 has two available slots.
    # driver_2 has one available slot.
    assert result.row_count == 3
    assert result.col_count == 2

    assert result.allowed_matrix == [
        [
            True,
            False,
        ],
        [
            True,
            False,
        ],
        [
            False,
            True,
        ],
    ]

    assert result.allowed_pair_count == 3
    assert result.forbidden_pair_count == 3


def test_dispatch_cost_breakdown_marks_forbidden_pairs():
    driver = DispatchDriver(
        driver_id="driver_1",
        lat=26.45,
        lon=80.35,
        current_load=0,
        max_capacity=1,
    )

    order = DispatchOrder(
        order_id="order_1",
        pickup_lat=26.46,
        pickup_lon=80.36,
    )

    result = build_dispatch_cost_matrix(
        drivers=[
            driver,
        ],
        orders=[
            order,
        ],
        distance_lookup=(
            lambda _driver, _order: (
                1_000_000_000.0
            )
        ),
        allowed_lookup=(
            lambda _driver, _order: False
        ),
    )

    assert result.allowed_matrix == [
        [
            False,
        ]
    ]

    assert len(
        result.breakdowns
    ) == 1

    assert (
        result.breakdowns[
            0
        ].allowed
        is False
    )


# ---------------------------------------------------------------------------
# Greedy feasibility tests
# ---------------------------------------------------------------------------


def test_greedy_never_selects_forbidden_pair():
    cost_matrix = [
        [
            1.0,
            2.0,
        ],
        [
            3.0,
            4.0,
        ],
    ]

    allowed_matrix = [
        [
            False,
            True,
        ],
        [
            True,
            True,
        ],
    ]

    result = solve_greedy_dispatch(
        cost_matrix,
        allowed_matrix=allowed_matrix,
    )

    for assignment in result.assignments:
        assert (
            allowed_matrix[
                assignment.row_index
            ][
                assignment.col_index
            ]
            is True
        )


def test_greedy_returns_no_assignment_when_every_pair_is_forbidden():
    result = solve_greedy_dispatch(
        [
            [
                1.0,
                2.0,
            ],
            [
                3.0,
                4.0,
            ],
        ],
        allowed_matrix=[
            [
                False,
                False,
            ],
            [
                False,
                False,
            ],
        ],
    )

    assert result.assignments == []
    assert result.assigned_count == 0

    assert result.unassigned_rows == [
        0,
        1,
    ]

    assert result.unassigned_cols == [
        0,
        1,
    ]


# ---------------------------------------------------------------------------
# Hungarian feasibility tests
# ---------------------------------------------------------------------------


def test_hungarian_never_selects_forbidden_pair():
    cost_matrix = [
        [
            1.0,
            2.0,
        ],
        [
            3.0,
            4.0,
        ],
    ]

    allowed_matrix = [
        [
            False,
            True,
        ],
        [
            True,
            True,
        ],
    ]

    result = solve_hungarian(
        cost_matrix,
        allowed_matrix=allowed_matrix,
    )

    for assignment in result.assignments:
        assert (
            allowed_matrix[
                assignment.row_index
            ][
                assignment.col_index
            ]
            is True
        )


def test_hungarian_avoids_cheaper_forbidden_replacement_cost():
    """
    The forbidden cell is deliberately the cheapest numeric value.

    Without the allowed matrix:

        row 0 -> col 1 = 1.0

    would look attractive.

    With explicit feasibility, Hungarian must never select it.
    """

    cost_matrix = [
        [
            100.0,
            1.0,
        ],
        [
            200.0,
            300.0,
        ],
    ]

    allowed_matrix = [
        [
            True,
            False,
        ],
        [
            True,
            True,
        ],
    ]

    result = solve_hungarian(
        cost_matrix,
        allowed_matrix=allowed_matrix,
    )

    assignment_pairs = {
        (
            assignment.row_index,
            assignment.col_index,
        )
        for assignment
        in result.assignments
    }

    assert (
        0,
        1,
    ) not in assignment_pairs

    assert assignment_pairs == {
        (
            0,
            0,
        ),
        (
            1,
            1,
        ),
    }


def test_hungarian_returns_no_assignment_when_every_pair_is_forbidden():
    result = solve_hungarian(
        [
            [
                1.0,
                2.0,
            ],
            [
                3.0,
                4.0,
            ],
        ],
        allowed_matrix=[
            [
                False,
                False,
            ],
            [
                False,
                False,
            ],
        ],
    )

    assert result.assignments == []
    assert result.assigned_count == 0

    assert result.unassigned_rows == [
        0,
        1,
    ]

    assert result.unassigned_cols == [
        0,
        1,
    ]


# ---------------------------------------------------------------------------
# Phase 10 real-road integration helpers
# ---------------------------------------------------------------------------


def _single_unreachable_payload() -> dict[
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
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4600,
                "pickup_lon": 80.3600,
            },
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": True,
    }


def _single_unreachable_dependencies(
) -> DispatchRoadMatrixDependencies:
    node_by_coordinate = {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 202,
    }

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return node_by_coordinate[
            (
                float(
                    lat
                ),
                float(
                    lon
                ),
            )
        ]

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        None,
    ]:
        assert source_node == 101

        return {
            target_node: None
            for target_node
            in target_nodes
        }

    return DispatchRoadMatrixDependencies(
        snap_node=snap_node,
        source_distance_builder=(
            source_distance_builder
        ),
    )


# ---------------------------------------------------------------------------
# Phase 10 service integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_real_road_unreachable_pair_is_not_assigned():
    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **_single_unreachable_payload()
        ),
        road_matrix_dependencies=(
            _single_unreachable_dependencies()
        ),
    )

    assert response.status == "ok"

    assert (
        response.matrix_algorithm
        == "source_dijkstra"
    )

    assert response.assigned_order_count == 0
    assert response.unassigned_order_count == 1

    assert (
        response.greedy.assigned_count
        == 0
    )

    assert (
        response.hungarian.assigned_count
        == 0
    )

    assert (
        response.greedy.assignments
        == []
    )

    assert (
        response.hungarian.assignments
        == []
    )


@pytest.mark.anyio
async def test_real_road_unreachable_pair_is_reported_in_telemetry():
    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **_single_unreachable_payload()
        ),
        road_matrix_dependencies=(
            _single_unreachable_dependencies()
        ),
    )

    assert response.road_network is not None

    assert (
        response.road_network.pair_count
        == 1
    )

    assert (
        response
        .road_network
        .reachable_pair_count
        == 0
    )

    assert (
        response
        .road_network
        .unreachable_pair_count
        == 1
    )

    assert (
        response
        .road_network
        .all_pairs_reachable
        is False
    )

    assert len(
        response
        .road_network
        .unreachable_pairs
    ) == 1

    pair = (
        response
        .road_network
        .unreachable_pairs[
            0
        ]
    )

    assert pair.driver_index == 0
    assert pair.order_index == 0
    assert pair.driver_node == 101
    assert pair.order_node == 202


@pytest.mark.anyio
async def test_unreachable_replacement_cost_is_not_selected_even_when_cheapest():
    """
    Prove that reachability, not the numeric replacement cost, controls
    assignment validity.

    The unreachable replacement cost is intentionally only 1 meter.

    Valid alternative assignments cost hundreds of meters.

    The unreachable pair must still never be selected.
    """

    payload = {
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
                "pickup_lat": 26.4700,
                "pickup_lon": 80.3700,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4800,
                "pickup_lon": 80.3800,
            },
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    node_by_coordinate = {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 102,
        (
            26.4700,
            80.3700,
        ): 201,
        (
            26.4800,
            80.3800,
        ): 202,
    }

    distances = {
        (
            101,
            201,
        ): 100.0,
        (
            101,
            202,
        ): None,
        (
            102,
            201,
        ): 200.0,
        (
            102,
            202,
        ): 300.0,
    }

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return node_by_coordinate[
            (
                float(
                    lat
                ),
                float(
                    lon
                ),
            )
        ]

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float | None,
    ]:
        return {
            target_node: distances[
                (
                    source_node,
                    target_node,
                )
            ]
            for target_node
            in target_nodes
        }

    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **payload
        ),
        road_matrix_dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snap_node,
                source_distance_builder=(
                    source_distance_builder
                ),
            )
        ),
        # Deliberately cheaper than every valid road cost.
        unreachable_cost_m=1.0,
    )

    hungarian_pairs = {
        (
            assignment.driver_id,
            assignment.order_id,
        )
        for assignment
        in response.hungarian.assignments
    }

    greedy_pairs = {
        (
            assignment.driver_id,
            assignment.order_id,
        )
        for assignment
        in response.greedy.assignments
    }

    forbidden_pair = (
        "driver_1",
        "order_2",
    )

    assert (
        forbidden_pair
        not in hungarian_pairs
    )

    assert (
        forbidden_pair
        not in greedy_pairs
    )

    assert (
        response.hungarian.assigned_count
        == 2
    )


@pytest.mark.anyio
async def test_reachable_alternative_driver_is_used_for_order():
    payload = {
        "drivers": [
            {
                "driver_id": "driver_unreachable",
                "lat": 26.4500,
                "lon": 80.3500,
                "current_load": 0,
                "max_capacity": 1,
            },
            {
                "driver_id": "driver_reachable",
                "lat": 26.4600,
                "lon": 80.3600,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4700,
                "pickup_lon": 80.3700,
            },
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    node_by_coordinate = {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 102,
        (
            26.4700,
            80.3700,
        ): 201,
    }

    distances = {
        (
            101,
            201,
        ): None,
        (
            102,
            201,
        ): 500.0,
    }

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return node_by_coordinate[
            (
                float(
                    lat
                ),
                float(
                    lon
                ),
            )
        ]

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float | None,
    ]:
        return {
            target_node: distances[
                (
                    source_node,
                    target_node,
                )
            ]
            for target_node
            in target_nodes
        }

    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **payload
        ),
        road_matrix_dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snap_node,
                source_distance_builder=(
                    source_distance_builder
                ),
            )
        ),
    )

    assert response.assigned_order_count == 1

    assert (
        response.hungarian.assigned_count
        == 1
    )

    assert (
        response.hungarian
        .assignments[
            0
        ]
        .driver_id
        == "driver_reachable"
    )

    assert (
        response.hungarian
        .assignments[
            0
        ]
        .order_id
        == "order_1"
    )


@pytest.mark.anyio
async def test_all_unreachable_real_road_matrix_returns_zero_assignments():
    payload = {
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
                "pickup_lat": 26.4700,
                "pickup_lon": 80.3700,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4800,
                "pickup_lon": 80.3800,
            },
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    node_by_coordinate = {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 102,
        (
            26.4700,
            80.3700,
        ): 201,
        (
            26.4800,
            80.3800,
        ): 202,
    }

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return node_by_coordinate[
            (
                float(
                    lat
                ),
                float(
                    lon
                ),
            )
        ]

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        None,
    ]:
        del source_node

        return {
            target_node: None
            for target_node
            in target_nodes
        }

    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **payload
        ),
        road_matrix_dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snap_node,
                source_distance_builder=(
                    source_distance_builder
                ),
            )
        ),
    )

    assert response.assigned_order_count == 0
    assert response.unassigned_order_count == 2

    assert (
        response.greedy.assigned_count
        == 0
    )

    assert (
        response.hungarian.assigned_count
        == 0
    )

    assert response.road_network is not None

    assert (
        response
        .road_network
        .unreachable_pair_count
        == 4
    )

    assert (
        response
        .road_network
        .reachable_pair_count
        == 0
    )


@pytest.mark.anyio
async def test_hungarian_can_assign_more_orders_than_greedy_under_reachability_constraints():
    """
    Restricted feasibility can expose the normal weakness of greedy.

    Matrix:

                    order_1    order_2

        driver_1      1.0        2.0
        driver_2      1.5         X

    Greedy:
        picks driver_1 -> order_1 first
        driver_2 cannot reach order_2
        result = 1 assignment

    Hungarian:
        driver_1 -> order_2
        driver_2 -> order_1
        result = 2 assignments
    """

    payload = {
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
                "pickup_lat": 26.4700,
                "pickup_lon": 80.3700,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4800,
                "pickup_lon": 80.3800,
            },
        ],
        "matrix_algorithm": (
            "source_dijkstra"
        ),
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    node_by_coordinate = {
        (
            26.4500,
            80.3500,
        ): 101,
        (
            26.4600,
            80.3600,
        ): 102,
        (
            26.4700,
            80.3700,
        ): 201,
        (
            26.4800,
            80.3800,
        ): 202,
    }

    distances = {
        (
            101,
            201,
        ): 1.0,
        (
            101,
            202,
        ): 2.0,
        (
            102,
            201,
        ): 1.5,
        (
            102,
            202,
        ): None,
    }

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        return node_by_coordinate[
            (
                float(
                    lat
                ),
                float(
                    lon
                ),
            )
        ]

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float | None,
    ]:
        return {
            target_node: distances[
                (
                    source_node,
                    target_node,
                )
            ]
            for target_node
            in target_nodes
        }

    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **payload
        ),
        road_matrix_dependencies=(
            DispatchRoadMatrixDependencies(
                snap_node=snap_node,
                source_distance_builder=(
                    source_distance_builder
                ),
            )
        ),
    )

    assert (
        response.greedy.assigned_count
        == 1
    )

    assert (
        response.hungarian.assigned_count
        == 2
    )

    # Phase 10 comparison correctly prioritizes assignment count before
    # comparing total cost.
    assert (
        response
        .comparison
        .hungarian_non_regression
        is True
    )

    hungarian_pairs = {
        (
            assignment.driver_id,
            assignment.order_id,
        )
        for assignment
        in response.hungarian.assignments
    }

    assert hungarian_pairs == {
        (
            "driver_1",
            "order_2",
        ),
        (
            "driver_2",
            "order_1",
        ),
    }


@pytest.mark.anyio
async def test_service_cost_breakdown_marks_unreachable_pair_as_not_allowed():
    response = await compare_dispatch_assignments(
        DispatchCompareRequest(
            **_single_unreachable_payload()
        ),
        road_matrix_dependencies=(
            _single_unreachable_dependencies()
        ),
    )

    assert len(
        response.cost_breakdown
    ) == 1

    breakdown = response.cost_breakdown[
        0
    ]

    assert breakdown.driver_id == "driver_1"
    assert breakdown.order_id == "order_1"

    assert breakdown.allowed is False