# tests/test_dispatch_road_cost_matrix.py

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.core.dispatch_road_cost_matrix import (
    RoadDispatchCostMatrixResult,
    RoadDispatchMatrixError,
    build_dispatch_road_cost_matrix,
)


def _build_mapping_source_builder(
    distances: dict[
        tuple[int, int],
        float | int | None,
    ],
    *,
    calls: list[
        tuple[
            int,
            tuple[int, ...],
        ]
    ]
    | None = None,
):
    """Build a deterministic source-distance callback for tests."""

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> dict[
        int,
        float | int | None,
    ]:
        normalized_targets = tuple(
            target_nodes
        )

        if calls is not None:
            calls.append(
                (
                    source_node,
                    normalized_targets,
                )
            )

        return {
            target_node: distances.get(
                (
                    source_node,
                    target_node,
                )
            )
            for target_node
            in normalized_targets
        }

    return source_distance_builder


def _matrix_as_lists(
    matrix: Sequence[
        Sequence[object]
    ],
) -> list[
    list[object]
]:
    """
    Normalize immutable tuple matrices to lists for readable assertions.

    The production core intentionally returns tuple-based matrices.
    """

    return [
        list(
            row
        )
        for row
        in matrix
    ]


def test_build_dispatch_road_cost_matrix_returns_result_type():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 125.5,
                }
            )
        ),
    )

    assert isinstance(
        result,
        RoadDispatchCostMatrixResult,
    )


def test_build_dispatch_road_cost_matrix_builds_rectangular_matrix():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
            2,
        ],
        order_nodes=[
            10,
            20,
            30,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): 200.0,
                    (
                        1,
                        30,
                    ): 300.0,
                    (
                        2,
                        10,
                    ): 400.0,
                    (
                        2,
                        20,
                    ): 500.0,
                    (
                        2,
                        30,
                    ): 600.0,
                }
            )
        ),
    )

    assert _matrix_as_lists(
        result.cost_matrix_m
    ) == [
        [
            100.0,
            200.0,
            300.0,
        ],
        [
            400.0,
            500.0,
            600.0,
        ],
    ]

    assert result.driver_count == 2
    assert result.order_count == 3
    assert result.pair_count == 6


def test_build_dispatch_road_cost_matrix_marks_reachable_pairs():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
            2,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): 200.0,
                    (
                        2,
                        10,
                    ): 300.0,
                    (
                        2,
                        20,
                    ): 400.0,
                }
            )
        ),
    )

    assert _matrix_as_lists(
        result.reachable_matrix
    ) == [
        [
            True,
            True,
        ],
        [
            True,
            True,
        ],
    ]

    assert result.reachable_pair_count == 4
    assert result.unreachable_pair_count == 0
    assert result.all_pairs_reachable is True
    assert result.unreachable_pairs == ()


def test_build_dispatch_road_cost_matrix_replaces_none_unreachable_distance():
    unreachable_cost_m = (
        1_000_000_000.0
    )

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 125.0,
                    (
                        1,
                        20,
                    ): None,
                }
            )
        ),
        unreachable_cost_m=(
            unreachable_cost_m
        ),
    )

    assert _matrix_as_lists(
        result.cost_matrix_m
    ) == [
        [
            125.0,
            unreachable_cost_m,
        ]
    ]

    assert _matrix_as_lists(
        result.reachable_matrix
    ) == [
        [
            True,
            False,
        ]
    ]

    assert result.reachable_pair_count == 1
    assert result.unreachable_pair_count == 1
    assert result.all_pairs_reachable is False


def test_build_dispatch_road_cost_matrix_replaces_positive_infinity():
    unreachable_cost_m = (
        999_999.0
    )

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): float(
                        "inf"
                    ),
                }
            )
        ),
        unreachable_cost_m=(
            unreachable_cost_m
        ),
    )

    assert _matrix_as_lists(
        result.cost_matrix_m
    ) == [
        [
            unreachable_cost_m,
        ]
    ]

    assert _matrix_as_lists(
        result.reachable_matrix
    ) == [
        [
            False,
        ]
    ]

    assert result.unreachable_pair_count == 1


def test_unreachable_pair_metadata_is_recorded():
    unreachable_cost_m = (
        123_456.0
    )

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            101,
        ],
        order_nodes=[
            202,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        101,
                        202,
                    ): None,
                }
            )
        ),
        unreachable_cost_m=(
            unreachable_cost_m
        ),
    )

    assert len(
        result.unreachable_pairs
    ) == 1

    pair = result.unreachable_pairs[
        0
    ]

    assert pair.driver_index == 0
    assert pair.order_index == 0
    assert pair.driver_node == 101
    assert pair.order_node == 202

    assert (
        pair.replacement_cost_m
        == unreachable_cost_m
    )


def test_same_graph_node_has_zero_distance():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            7,
        ],
        order_nodes=[
            7,
            8,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        7,
                        7,
                    ): 999.0,
                    (
                        7,
                        8,
                    ): 25.0,
                }
            )
        ),
    )

    assert (
        result.cost_matrix_m[
            0
        ][
            0
        ]
        == 0.0
    )

    assert (
        result.reachable_matrix[
            0
        ][
            0
        ]
        is True
    )


def test_duplicate_driver_nodes_reuse_one_source_search():
    calls: list[
        tuple[
            int,
            tuple[int, ...],
        ]
    ] = []

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
            1,
            2,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): 200.0,
                    (
                        2,
                        10,
                    ): 300.0,
                    (
                        2,
                        20,
                    ): 400.0,
                },
                calls=calls,
            )
        ),
    )

    assert result.unique_driver_node_count == 2
    assert result.source_search_count == 2

    assert [
        call[
            0
        ]
        for call
        in calls
    ] == [
        1,
        2,
    ]

    assert (
        result.cost_matrix_m[
            0
        ]
        == result.cost_matrix_m[
            1
        ]
    )


def test_duplicate_order_nodes_reuse_unique_target_distance():
    calls: list[
        tuple[
            int,
            tuple[int, ...],
        ]
    ] = []

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): 200.0,
                },
                calls=calls,
            )
        ),
    )

    assert result.unique_order_node_count == 2

    assert calls == [
        (
            1,
            (
                10,
                20,
            ),
        )
    ]

    assert _matrix_as_lists(
        result.cost_matrix_m
    ) == [
        [
            100.0,
            100.0,
            200.0,
        ]
    ]


def test_driver_and_order_node_order_is_preserved():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            30,
            10,
            20,
        ],
        order_nodes=[
            300,
            100,
            200,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        30,
                        300,
                    ): 1.0,
                    (
                        30,
                        100,
                    ): 2.0,
                    (
                        30,
                        200,
                    ): 3.0,
                    (
                        10,
                        300,
                    ): 4.0,
                    (
                        10,
                        100,
                    ): 5.0,
                    (
                        10,
                        200,
                    ): 6.0,
                    (
                        20,
                        300,
                    ): 7.0,
                    (
                        20,
                        100,
                    ): 8.0,
                    (
                        20,
                        200,
                    ): 9.0,
                }
            )
        ),
    )

    assert result.driver_nodes == (
        30,
        10,
        20,
    )

    assert result.order_nodes == (
        300,
        100,
        200,
    )


def test_sequence_source_builder_is_supported():
    distances = {
        (
            1,
            10,
        ): 100.0,
        (
            1,
            20,
        ): 200.0,
        (
            2,
            10,
        ): 300.0,
        (
            2,
            20,
        ): 400.0,
    }

    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> list[float]:
        return [
            distances[
                (
                    source_node,
                    target_node,
                )
            ]
            for target_node
            in target_nodes
        ]

    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
            2,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            source_distance_builder
        ),
    )

    assert _matrix_as_lists(
        result.cost_matrix_m
    ) == [
        [
            100.0,
            200.0,
        ],
        [
            300.0,
            400.0,
        ],
    ]


def test_cost_at_returns_expected_matrix_value():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 111.0,
                    (
                        1,
                        20,
                    ): 222.0,
                }
            )
        ),
    )

    assert result.cost_at(
        0,
        0,
    ) == 111.0

    assert result.cost_at(
        0,
        1,
    ) == 222.0


def test_is_reachable_returns_expected_value():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
            20,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): None,
                }
            )
        ),
    )

    assert result.is_reachable(
        0,
        0,
    ) is True

    assert result.is_reachable(
        0,
        1,
    ) is False


def test_build_time_is_non_negative():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
        ],
        order_nodes=[
            10,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                }
            )
        ),
    )

    assert result.build_time_ms >= 0.0


def test_rejects_empty_driver_nodes():
    with pytest.raises(
        ValueError,
        match=(
            "driver_nodes must contain "
            "at least one graph node"
        ),
    ):
        build_dispatch_road_cost_matrix(
            driver_nodes=[],
            order_nodes=[
                10,
            ],
            source_distance_builder=(
                _build_mapping_source_builder(
                    {}
                )
            ),
        )


def test_rejects_empty_order_nodes():
    with pytest.raises(
        ValueError,
        match=(
            "order_nodes must contain "
            "at least one graph node"
        ),
    ):
        build_dispatch_road_cost_matrix(
            driver_nodes=[
                1,
            ],
            order_nodes=[],
            source_distance_builder=(
                _build_mapping_source_builder(
                    {}
                )
            ),
        )


@pytest.mark.parametrize(
    "unreachable_cost_m",
    [
        0.0,
        -1.0,
        float(
            "nan"
        ),
        float(
            "inf"
        ),
        float(
            "-inf"
        ),
    ],
)
def test_rejects_invalid_unreachable_cost(
    unreachable_cost_m: float,
):
    with pytest.raises(
        ValueError
    ):
        build_dispatch_road_cost_matrix(
            driver_nodes=[
                1,
            ],
            order_nodes=[
                10,
            ],
            source_distance_builder=(
                _build_mapping_source_builder(
                    {
                        (
                            1,
                            10,
                        ): 100.0,
                    }
                )
            ),
            unreachable_cost_m=(
                unreachable_cost_m
            ),
        )


@pytest.mark.parametrize(
    "invalid_distance",
    [
        -1.0,
        float(
            "nan"
        ),
        float(
            "-inf"
        ),
    ],
)
def test_rejects_invalid_source_distance(
    invalid_distance: float,
):
    with pytest.raises(
        RoadDispatchMatrixError
    ):
        build_dispatch_road_cost_matrix(
            driver_nodes=[
                1,
            ],
            order_nodes=[
                10,
            ],
            source_distance_builder=(
                _build_mapping_source_builder(
                    {
                        (
                            1,
                            10,
                        ): invalid_distance,
                    }
                )
            ),
        )


def test_rejects_sequence_builder_with_wrong_length():
    def source_distance_builder(
        source_node: int,
        target_nodes: Sequence[int],
    ) -> list[float]:
        del source_node
        del target_nodes

        return [
            100.0,
        ]

    with pytest.raises(
        RoadDispatchMatrixError
    ):
        build_dispatch_road_cost_matrix(
            driver_nodes=[
                1,
            ],
            order_nodes=[
                10,
                20,
            ],
            source_distance_builder=(
                source_distance_builder
            ),
        )


def test_mixed_reachable_and_unreachable_pairs_have_correct_counts():
    result = build_dispatch_road_cost_matrix(
        driver_nodes=[
            1,
            2,
        ],
        order_nodes=[
            10,
            20,
            30,
        ],
        source_distance_builder=(
            _build_mapping_source_builder(
                {
                    (
                        1,
                        10,
                    ): 100.0,
                    (
                        1,
                        20,
                    ): None,
                    (
                        1,
                        30,
                    ): 300.0,
                    (
                        2,
                        10,
                    ): None,
                    (
                        2,
                        20,
                    ): 500.0,
                    (
                        2,
                        30,
                    ): None,
                }
            )
        ),
    )

    assert result.pair_count == 6
    assert result.reachable_pair_count == 3
    assert result.unreachable_pair_count == 3

    assert _matrix_as_lists(
        result.reachable_matrix
    ) == [
        [
            True,
            False,
            True,
        ],
        [
            False,
            True,
            False,
        ],
    ]

    assert len(
        result.unreachable_pairs
    ) == 3