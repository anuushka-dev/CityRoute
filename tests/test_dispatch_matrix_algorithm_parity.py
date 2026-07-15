# tests/test_dispatch_matrix_algorithm_parity.py

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.core.dispatch_cost_matrix import (
    haversine_m,
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
    """Run pytest-anyio tests with asyncio only."""

    return "asyncio"


def _base_payload(
    *,
    matrix_algorithm: str,
    use_cache: bool = False,
    load_penalty_m: float = 0.0,
    slot_penalty_m: float = 0.0,
    return_cost_breakdown: bool = False,
) -> dict[str, Any]:
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
            {
                "driver_id": "driver_3",
                "lat": 26.4700,
                "lon": 80.3700,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4501,
                "pickup_lon": 80.3321,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4602,
                "pickup_lon": 80.3502,
            },
            {
                "order_id": "order_3",
                "pickup_lat": 26.4702,
                "pickup_lon": 80.3702,
            },
        ],
        "matrix_algorithm": matrix_algorithm,
        "use_cache": use_cache,
        "load_penalty_m": load_penalty_m,
        "slot_penalty_m": slot_penalty_m,
        "return_cost_breakdown": return_cost_breakdown,
    }


def _capacity_payload(
    *,
    matrix_algorithm: str,
) -> dict[str, Any]:
    """
    Build a request with more orders than available capacity.

    Available slots:
        driver_1 -> 2
        driver_2 -> 1

    Total:
        3 slots
        4 orders
    """

    return {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.4499,
                "lon": 80.3319,
                "current_load": 0,
                "max_capacity": 2,
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
                "pickup_lat": 26.4501,
                "pickup_lon": 80.3321,
            },
            {
                "order_id": "order_2",
                "pickup_lat": 26.4510,
                "pickup_lon": 80.3330,
            },
            {
                "order_id": "order_3",
                "pickup_lat": 26.4602,
                "pickup_lon": 80.3502,
            },
            {
                "order_id": "order_4",
                "pickup_lat": 26.4700,
                "pickup_lon": 80.3700,
            },
        ],
        "matrix_algorithm": matrix_algorithm,
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }


def _build_equivalent_road_dependencies(
    payload: dict[str, Any],
) -> tuple[
    DispatchRoadMatrixDependencies,
    dict[
        tuple[float, float],
        int,
    ],
]:
    """
    Build fake road dependencies whose source-Dijkstra distances are exactly
    equal to the Haversine distances for the same request.

    This creates a controlled parity oracle:

        Haversine matrix == source_dijkstra matrix

    Therefore Greedy and Hungarian should receive equivalent optimization
    inputs from both algorithm paths.
    """

    node_by_coordinate: dict[
        tuple[float, float],
        int,
    ] = {}

    coordinate_by_node: dict[
        int,
        tuple[float, float],
    ] = {}

    next_node_id = 1_000

    coordinates: list[
        tuple[float, float]
    ] = []

    for driver in payload[
        "drivers"
    ]:
        coordinates.append(
            (
                float(
                    driver[
                        "lat"
                    ]
                ),
                float(
                    driver[
                        "lon"
                    ]
                ),
            )
        )

    for order in payload[
        "orders"
    ]:
        coordinates.append(
            (
                float(
                    order[
                        "pickup_lat"
                    ]
                ),
                float(
                    order[
                        "pickup_lon"
                    ]
                ),
            )
        )

    for coordinate in coordinates:
        if (
            coordinate
            in node_by_coordinate
        ):
            continue

        node_by_coordinate[
            coordinate
        ] = next_node_id

        coordinate_by_node[
            next_node_id
        ] = coordinate

        next_node_id += 1

    def snap_node(
        lat: float,
        lon: float,
    ) -> int:
        coordinate = (
            float(
                lat
            ),
            float(
                lon
            ),
        )

        try:
            return node_by_coordinate[
                coordinate
            ]

        except KeyError as exc:
            raise AssertionError(
                "Unexpected coordinate passed to "
                "test snap adapter: "
                f"{coordinate}"
            ) from exc

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[int, float]:
        source_lat, source_lon = (
            coordinate_by_node[
                source_node
            ]
        )

        result: dict[
            int,
            float,
        ] = {}

        for target_node in target_nodes:
            target_lat, target_lon = (
                coordinate_by_node[
                    target_node
                ]
            )

            result[
                target_node
            ] = haversine_m(
                source_lat,
                source_lon,
                target_lat,
                target_lon,
            )

        return result

    return (
        DispatchRoadMatrixDependencies(
            snap_node=(
                snap_node
            ),
            source_distance_builder=(
                source_distance_builder
            ),
        ),
        node_by_coordinate,
    )


def _assignment_signature(
    assignments: Sequence[Any],
) -> list[
    tuple[
        str,
        str,
        int,
        int,
    ]
]:
    """
    Compare assignment identity without depending on float formatting.
    """

    return [
        (
            assignment.driver_id,
            assignment.order_id,
            assignment.row_index,
            assignment.col_index,
        )
        for assignment
        in assignments
    ]


@pytest.mark.anyio
async def test_haversine_and_equivalent_source_dijkstra_have_greedy_assignment_parity():
    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        _assignment_signature(
            haversine_response
            .greedy
            .assignments
        )
        == _assignment_signature(
            road_response
            .greedy
            .assignments
        )
    )

    assert (
        haversine_response
        .greedy
        .assigned_count
        == road_response
        .greedy
        .assigned_count
    )


@pytest.mark.anyio
async def test_haversine_and_equivalent_source_dijkstra_have_hungarian_assignment_parity():
    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        _assignment_signature(
            haversine_response
            .hungarian
            .assignments
        )
        == _assignment_signature(
            road_response
            .hungarian
            .assignments
        )
    )

    assert (
        haversine_response
        .hungarian
        .assigned_count
        == road_response
        .hungarian
        .assigned_count
    )


@pytest.mark.anyio
async def test_haversine_and_equivalent_source_dijkstra_have_cost_parity():
    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        road_response
        .greedy
        .total_cost
        == pytest.approx(
            haversine_response
            .greedy
            .total_cost,
            abs=1e-6,
        )
    )

    assert (
        road_response
        .hungarian
        .total_cost
        == pytest.approx(
            haversine_response
            .hungarian
            .total_cost,
            abs=1e-6,
        )
    )


@pytest.mark.anyio
async def test_matrix_algorithms_preserve_capacity_and_assignment_counts():
    haversine_payload = (
        _capacity_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _capacity_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        haversine_response
        .available_slot_count
        == 3
    )

    assert (
        road_response
        .available_slot_count
        == 3
    )

    assert (
        haversine_response
        .order_count
        == 4
    )

    assert (
        road_response
        .order_count
        == 4
    )

    assert (
        haversine_response
        .assigned_order_count
        == 3
    )

    assert (
        road_response
        .assigned_order_count
        == 3
    )

    assert (
        haversine_response
        .unassigned_order_count
        == 1
    )

    assert (
        road_response
        .unassigned_order_count
        == 1
    )


@pytest.mark.anyio
async def test_source_dijkstra_has_road_telemetry_while_haversine_does_not():
    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        haversine_response
        .road_network
        is None
    )

    assert (
        road_response
        .road_network
        is not None
    )

    assert (
        road_response
        .matrix_algorithm
        == "source_dijkstra"
    )

    assert (
        road_response
        .road_network
        .matrix_source
        == "computed"
    )

    assert (
        road_response
        .road_network
        .snapped_driver_count
        == 3
    )

    assert (
        road_response
        .road_network
        .snapped_order_count
        == 3
    )

    assert (
        road_response
        .road_network
        .pair_count
        == 9
    )

    assert (
        road_response
        .road_network
        .reachable_pair_count
        == 9
    )

    assert (
        road_response
        .road_network
        .unreachable_pair_count
        == 0
    )

    assert (
        road_response
        .road_network
        .all_pairs_reachable
        is True
    )


@pytest.mark.anyio
async def test_equivalent_algorithms_preserve_cost_breakdown_and_penalties():
    load_penalty_m = 75.0
    slot_penalty_m = 25.0

    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            ),
            load_penalty_m=(
                load_penalty_m
            ),
            slot_penalty_m=(
                slot_penalty_m
            ),
            return_cost_breakdown=True,
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            ),
            load_penalty_m=(
                load_penalty_m
            ),
            slot_penalty_m=(
                slot_penalty_m
            ),
            return_cost_breakdown=True,
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        len(
            haversine_response
            .cost_breakdown
        )
        == 9
    )

    assert (
        len(
            road_response
            .cost_breakdown
        )
        == 9
    )

    for (
        haversine_cell,
        road_cell,
    ) in zip(
        haversine_response
        .cost_breakdown,
        road_response
        .cost_breakdown,
        strict=True,
    ):
        assert (
            haversine_cell.row_index
            == road_cell.row_index
        )

        assert (
            haversine_cell.col_index
            == road_cell.col_index
        )

        assert (
            haversine_cell.driver_id
            == road_cell.driver_id
        )

        assert (
            haversine_cell.order_id
            == road_cell.order_id
        )

        assert (
            road_cell.distance_m
            == pytest.approx(
                haversine_cell.distance_m,
                abs=1e-6,
            )
        )

        assert (
            road_cell.load_penalty_m
            == pytest.approx(
                haversine_cell.load_penalty_m,
                abs=1e-6,
            )
        )

        assert (
            road_cell.slot_penalty_m
            == pytest.approx(
                haversine_cell.slot_penalty_m,
                abs=1e-6,
            )
        )

        assert (
            road_cell.total_cost
            == pytest.approx(
                haversine_cell.total_cost,
                abs=1e-6,
            )
        )


@pytest.mark.anyio
async def test_matrix_algorithms_preserve_hungarian_non_regression():
    haversine_payload = (
        _base_payload(
            matrix_algorithm=(
                "haversine"
            )
        )
    )

    road_payload = (
        _base_payload(
            matrix_algorithm=(
                "source_dijkstra"
            )
        )
    )

    (
        road_dependencies,
        _,
    ) = (
        _build_equivalent_road_dependencies(
            road_payload
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    assert (
        haversine_response
        .comparison
        .hungarian_non_regression
        is True
    )

    assert (
        road_response
        .comparison
        .hungarian_non_regression
        is True
    )


@pytest.mark.anyio
async def test_unreachable_road_pair_is_forbidden_instead_of_matching_haversine():
    """
    This test proves the intentional difference between the algorithms.

    Haversine:
        every coordinate pair has a straight-line distance.

    Directed road network:
        a pair may be unreachable.

    The road path must therefore return no assignment for an unreachable
    pair rather than blindly matching Haversine behavior.
    """

    haversine_payload = {
        "drivers": [
            {
                "driver_id": "driver_1",
                "lat": 26.4499,
                "lon": 80.3319,
                "current_load": 0,
                "max_capacity": 1,
            },
        ],
        "orders": [
            {
                "order_id": "order_1",
                "pickup_lat": 26.4600,
                "pickup_lon": 80.3500,
            },
        ],
        "matrix_algorithm": "haversine",
        "use_cache": False,
        "load_penalty_m": 0.0,
        "slot_penalty_m": 0.0,
        "return_cost_breakdown": False,
    }

    road_payload = {
        **haversine_payload,
        "matrix_algorithm": (
            "source_dijkstra"
        ),
    }

    driver_coordinate = (
        26.4499,
        80.3319,
    )

    order_coordinate = (
        26.4600,
        80.3500,
    )

    node_by_coordinate = {
        driver_coordinate: 101,
        order_coordinate: 202,
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

    road_dependencies = (
        DispatchRoadMatrixDependencies(
            snap_node=(
                snap_node
            ),
            source_distance_builder=(
                source_distance_builder
            ),
        )
    )

    haversine_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **haversine_payload
            )
        )
    )

    road_response = (
        await compare_dispatch_assignments(
            DispatchCompareRequest(
                **road_payload
            ),
            road_matrix_dependencies=(
                road_dependencies
            ),
        )
    )

    # Straight-line path can assign the order.
    assert (
        haversine_response
        .assigned_order_count
        == 1
    )

    assert (
        haversine_response
        .hungarian
        .assigned_count
        == 1
    )

    # Directed road path cannot.
    assert (
        road_response
        .assigned_order_count
        == 0
    )

    assert (
        road_response
        .unassigned_order_count
        == 1
    )

    assert (
        road_response
        .hungarian
        .assigned_count
        == 0
    )

    assert (
        road_response
        .greedy
        .assigned_count
        == 0
    )

    assert (
        road_response
        .hungarian
        .assignments
        == []
    )

    assert (
        road_response
        .greedy
        .assignments
        == []
    )

    assert (
        road_response
        .road_network
        is not None
    )

    assert (
        road_response
        .road_network
        .reachable_pair_count
        == 0
    )

    assert (
        road_response
        .road_network
        .unreachable_pair_count
        == 1
    )

    assert (
        road_response
        .road_network
        .all_pairs_reachable
        is False
    )